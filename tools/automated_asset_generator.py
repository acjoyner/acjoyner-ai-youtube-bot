"""
automated_asset_generator.py
-----------------------------
Generates all visual assets for a Finance video automatically:

  1. Parses the structured scene script from the DB.
  2. Builds a DALL-E 3 image prompt from the Master Character Descriptor (MCD)
     + the scene ACTION — ensuring mascot consistency across every scene.
  3. Sends each prompt to OpenAI DALL-E 3 → gets an image URL.
  4. Sends each image URL to fal.ai Kling (image-to-video) → gets a 5-second
     animated video clip URL.
  5. Downloads every image and clip locally to:
       static/assets/<record_id>/scene_<n>.png
       static/assets/<record_id>/scene_<n>.mp4
  6. Generates per-scene TTS audio (edge-tts) for the DIALOGUE:
       static/assets/<record_id>/audio_<n>.mp3
  7. Saves the completed scene_data JSON array back to the DB.
  8. Updates auto_prod_status at each phase so the dashboard can show progress.

Required .env keys:
  OPENAI_API_KEY   — OpenAI API key (for DALL-E 3)
  FAL_KEY          — fal.ai API key  (for Kling image-to-video)
"""

import os
import sys
import json
import asyncio
import sqlite3
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_FILE      = os.getenv("DB_FILE", "youtube.db")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY")
# Accept either FAL_KEY or FAL_API_KEY — whichever is in .env
FAL_KEY      = os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")

# fal.ai client reads FAL_KEY from the environment
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY


def _check_credentials():
    """Raise a clear error early if required API keys are missing."""
    missing = []
    if not OPENAI_KEY:
        missing.append("OPENAI_API_KEY  — get yours at https://platform.openai.com/api-keys")
    if not FAL_KEY:
        missing.append("FAL_KEY or FAL_API_KEY — get yours at https://fal.ai (free credits on signup)")
    if missing:
        raise EnvironmentError(
            "Missing required API keys in .env:\n" + "\n".join(f"  • {m}" for m in missing)
        )

# ---------------------------------------------------------------------------
# Master Character Descriptor — prepended to every DALL-E 3 prompt.
# This is what keeps the mascot visually consistent across all scenes.
# ---------------------------------------------------------------------------

MCD = (
    "A Family Guy-inspired cartoon of a Black male finance expert. "
    "He has a rounded afro, thin-rimmed gold glasses, a goatee, and a wide smile with white teeth. "
    "He is wearing a tailored navy blue business suit, a white dress shirt, and a gold-and-navy striped tie. "
    "Art style: Flat vector colors, thick bold black outlines, simple shading, "
    "centered full-body composition, high resolution, white background."
)

# Motion prompt sent to Kling for every clip — only the character moves.
MOTION_PROMPT = (
    "The cartoon character subtly gestures while speaking — slight hand movement, "
    "natural head nod. Smooth 5-second animation. Only the character moves. "
    "Background stays static. Flat cartoon art style maintained throughout."
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _set_status(record_id: str, status: str, auto_prod_status: str = None):
    conn = _get_db()
    if auto_prod_status is not None:
        conn.execute(
            "UPDATE Videos SET Status = ?, auto_prod_status = ? WHERE record_id = ?",
            (status, auto_prod_status, record_id)
        )
    else:
        conn.execute(
            "UPDATE Videos SET Status = ? WHERE record_id = ?",
            (status, record_id)
        )
    conn.commit()
    conn.close()


def _set_auto_prod_status(record_id: str, auto_prod_status: str):
    conn = _get_db()
    conn.execute(
        "UPDATE Videos SET auto_prod_status = ? WHERE record_id = ?",
        (auto_prod_status, record_id)
    )
    conn.commit()
    conn.close()


def _save_scene_data(record_id: str, scenes: list):
    conn = _get_db()
    conn.execute(
        "UPDATE Videos SET scene_data = ? WHERE record_id = ?",
        (json.dumps(scenes), record_id)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DALL-E 3 image generation
# ---------------------------------------------------------------------------

def generate_image(scene_action: str, output_path: Path) -> str:
    """
    Generate one image via DALL-E 3.
    Returns the local file path.
    """
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)

    full_prompt = f"{MCD} {scene_action}"

    response = client.images.generate(
        model="dall-e-3",
        prompt=full_prompt,
        size="1792x1024",   # 16:9 landscape
        quality="standard",
        n=1,
    )
    image_url = response.data[0].url

    # Download and save locally
    r = requests.get(image_url, timeout=60)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Image saved: {output_path}")
    return image_url


# ---------------------------------------------------------------------------
# fal.ai Kling image-to-video
# ---------------------------------------------------------------------------

def generate_clip(image_path: Path, output_path: Path) -> str:
    """
    Submit an image-to-video job to fal.ai Kling.
    Returns the remote video URL (clip is also saved locally).
    """
    import fal_client

    # fal.ai needs the image uploaded or accessible via URL.
    # Upload local image to fal.ai storage first.
    print(f"    Uploading image to fal.ai storage...")
    with open(image_path, "rb") as f:
        image_url = fal_client.upload(f.read(), content_type="image/png")

    print(f"    Submitting Kling image-to-video job...")
    result = fal_client.run(
        "fal-ai/kling-video/v1/standard/image-to-video",
        arguments={
            "image_url":    image_url,
            "prompt":       MOTION_PROMPT,
            "duration":     "5",
            "aspect_ratio": "16:9",
        }
    )

    video_url = result["video"]["url"]

    # Download clip locally
    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Clip saved: {output_path}")
    return video_url


# ---------------------------------------------------------------------------
# Per-scene TTS voiceover
# ---------------------------------------------------------------------------

async def _tts(text: str, output_path: str):
    import edge_tts
    voice = "en-US-GuyNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_scene_audio(dialogue: str, output_path: Path) -> Path:
    """Generate a short MP3 for one scene's dialogue."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_tts(dialogue, str(output_path)))
    print(f"    Audio saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_assets(record_id: str, script: str) -> list[dict]:
    """
    Full asset generation pipeline for one video.

    Phases:
      pending      → iterating through scenes
      images_done  → all DALL-E 3 images downloaded
      clips_done   → all Kling video clips downloaded + audio generated
      done         → scene_data saved to DB

    Returns the completed scene list.
    """
    _check_credentials()   # fail fast with a clear message if keys missing

    from tools.rewrite_script import parse_scenes

    scenes = parse_scenes(script)
    if not scenes:
        raise ValueError("No scenes found in script. Make sure the script uses [SCENE N] format.")

    assets_dir = Path("static") / "assets" / record_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[Asset Generator] {len(scenes)} scenes found for record {record_id}")

    # -----------------------------------------------------------------------
    # Phase 1: Generate DALL-E 3 images
    # -----------------------------------------------------------------------
    print("\n--- Phase 1: Generating images (DALL-E 3) ---")
    _set_auto_prod_status(record_id, "pending")

    for scene in scenes:
        n = scene["index"]
        img_path = assets_dir / f"scene_{n}.png"
        print(f"  Scene {n + 1}/{len(scenes)}: {scene['action'][:60]}...")

        if img_path.exists():
            print(f"    (cached)")
            scene["image_url"] = None   # don't re-store remote URL after restart
        else:
            scene["image_url"] = generate_image(scene["action"], img_path)

        scene["image_local"] = str(img_path)
        _save_scene_data(record_id, scenes)   # checkpoint after each image

    _set_auto_prod_status(record_id, "images_done")
    print("Phase 1 complete — all images generated.")

    # -----------------------------------------------------------------------
    # Phase 2: Generate Kling video clips + per-scene audio
    # -----------------------------------------------------------------------
    print("\n--- Phase 2: Generating video clips (fal.ai Kling) + audio ---")

    for scene in scenes:
        n = scene["index"]
        img_path  = assets_dir / f"scene_{n}.png"
        clip_path = assets_dir / f"scene_{n}.mp4"
        audio_path = assets_dir / f"audio_{n}.mp3"

        print(f"  Scene {n + 1}/{len(scenes)}")

        # Video clip
        if clip_path.exists():
            print(f"    Clip cached: {clip_path}")
            scene["clip_path"] = str(clip_path)
        else:
            scene["clip_url"]  = generate_clip(img_path, clip_path)
            scene["clip_path"] = str(clip_path)

        # Audio
        if audio_path.exists():
            print(f"    Audio cached: {audio_path}")
        else:
            generate_scene_audio(scene["dialogue"], audio_path)
        scene["audio_path"] = str(audio_path)

        _save_scene_data(record_id, scenes)   # checkpoint after each clip

    _set_auto_prod_status(record_id, "clips_done")
    print("Phase 2 complete — all clips and audio generated.")

    return scenes


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python automated_asset_generator.py <record_id>")
        sys.exit(1)

    record_id = sys.argv[1]
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT Script FROM Videos WHERE record_id = ?", (record_id,)).fetchone()
    conn.close()

    if not row or not row["Script"]:
        print("No script found for that record_id.")
        sys.exit(1)

    scenes = generate_assets(record_id, row["Script"])
    print(f"\nDone. {len(scenes)} scenes processed.")
