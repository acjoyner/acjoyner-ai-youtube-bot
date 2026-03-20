"""
automated_asset_generator.py
-----------------------------
Generates all assets for a Finance video — 4 phases:

  1. DALL-E 3       → scene PNG  (static/assets/<id>/scene_<n>.png)
  2. ElevenLabs     → scene MP3  (static/assets/<id>/audio_<n>.mp3)
  3. Kling i2v      → animated MP4 clip from the still image
                       (static/assets/<id>/clip_<n>.mp4)
  4. Kling lipsync  → lip-synced MP4 from clip + audio
                       (static/assets/<id>/lipsync_<n>.mp4)

Scene dicts saved to DB after every step so the dashboard always shows
the latest state even if the process is interrupted.

Required .env keys:
  OPENAI_API_KEY       — DALL-E 3 (~$0.04/image)
  ELEVENLABS_API_KEY   — ElevenLabs TTS
  FAL_API_KEY          — fal.ai Kling i2v + lipsync
"""

import os
import sys
import json
import sqlite3
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_FILE         = os.getenv("DB_FILE", "youtube.db")
OPENAI_KEY      = os.getenv("OPENAI_API_KEY")
ELEVENLABS_KEY  = os.getenv("ELEVENLABS_API_KEY")
FAL_KEY         = os.getenv("FAL_API_KEY") or os.getenv("FAL_KEY")

# ---------------------------------------------------------------------------
# Voice & model config — swap voice ID here to change character voice
# ---------------------------------------------------------------------------
VOICE_ID        = "nPczCjzI2devNBz1zQrb"   # Brian — Deep, Resonant, Classy American
ELEVEN_MODEL    = "eleven_multilingual_v2"  # Best accent consistency

# ---------------------------------------------------------------------------
# fal.ai Kling endpoints — update here if fal.ai renames them
# ---------------------------------------------------------------------------
KLING_I2V_MODEL      = "fal-ai/kling-video/v2.1/standard/image-to-video"
KLING_LIPSYNC_MODEL  = "fal-ai/sync-lipsync"

# ---------------------------------------------------------------------------
# Master Character Descriptor — prepended to every DALL-E 3 prompt
# ---------------------------------------------------------------------------
MCD = (
    "A Family Guy-inspired cartoon of a Black male finance expert. "
    "He has a rounded afro, thin-rimmed gold glasses, a goatee, and a wide smile with white teeth. "
    "He is wearing a tailored navy blue business suit, a white dress shirt, and a gold-and-navy striped tie. "
    "Art style: Flat vector colors, thick bold black outlines, simple shading, "
    "centered full-body composition, high resolution, white background."
)


# ---------------------------------------------------------------------------
# Credential check
# ---------------------------------------------------------------------------

def _check_credentials():
    missing = []
    if not OPENAI_KEY:
        missing.append("OPENAI_API_KEY")
    if not ELEVENLABS_KEY:
        missing.append("ELEVENLABS_API_KEY")
    if not FAL_KEY:
        missing.append("FAL_API_KEY")
    if missing:
        raise EnvironmentError(
            f"Missing keys in .env: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _set_status(record_id: str, status: str):
    conn = _get_db()
    conn.execute("UPDATE Videos SET auto_prod_status = ? WHERE record_id = ?", (status, record_id))
    conn.commit()
    conn.close()


def _save_scene_data(record_id: str, scenes: list):
    conn = _get_db()
    conn.execute("UPDATE Videos SET scene_data = ? WHERE record_id = ?", (json.dumps(scenes), record_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Phase 1 — DALL-E 3 image generation
# ---------------------------------------------------------------------------

def generate_image(scene_action: str, output_path: Path) -> str:
    """Generate one scene image via DALL-E 3. Returns the remote URL."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)

    response = client.images.generate(
        model="dall-e-3",
        prompt=f"{MCD} {scene_action}",
        size="1792x1024",
        quality="standard",
        n=1,
    )
    image_url = response.data[0].url

    r = requests.get(image_url, timeout=60)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Image saved: {output_path}")
    return image_url


# ---------------------------------------------------------------------------
# Phase 2 — ElevenLabs TTS audio
# ---------------------------------------------------------------------------

def generate_scene_audio(dialogue: str, output_path: Path) -> Path:
    """Generate per-scene MP3 via ElevenLabs."""
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_KEY)
    audio_stream = client.text_to_speech.convert(
        text=dialogue,
        voice_id=VOICE_ID,
        model_id=ELEVEN_MODEL,
        output_format="mp3_44100_128",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)

    print(f"    Audio saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Phase 3 — Kling image-to-video
# ---------------------------------------------------------------------------

def generate_kling_clip(image_path: str, output_path: Path) -> Path:
    """Animate a still image into a 5-second video clip via Kling i2v."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY

    print(f"    Uploading image to fal.ai storage...")
    image_url = fal_client.upload_file(image_path)

    print(f"    Submitting Kling i2v job...")
    handler = fal_client.submit(
        KLING_I2V_MODEL,
        arguments={
            "image_url": image_url,
            "prompt": (
                "The cartoon character makes natural, expressive gestures — "
                "slight head nod, hand movement, confident body language. "
                "Smooth animation, character stays on screen."
            ),
            "duration": "10",
            "aspect_ratio": "16:9",
            "negative_prompt": "distorted face, blurry, morphing, text, watermark",
        },
    )
    result = handler.get()
    video_url = result["video"]["url"]

    r = requests.get(video_url, timeout=120)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Clip saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Phase 4 — Kling lipsync
# ---------------------------------------------------------------------------

def apply_lipsync(clip_path: str, audio_path: str, output_path: Path) -> Path:
    """Apply lip-sync to an animated clip using the scene audio."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY

    print(f"    Uploading clip + audio for lipsync...")
    video_url = fal_client.upload_file(clip_path)
    audio_url = fal_client.upload_file(audio_path)

    print(f"    Submitting Kling lipsync job...")
    handler = fal_client.submit(
        KLING_LIPSYNC_MODEL,
        arguments={
            "video_url": video_url,
            "audio_url": audio_url,
            "sync_mode": "bounce",   # smoother sync than default
            "enhance_quality": True,
        },
    )
    result = handler.get()
    output_url = result["video"]["url"]

    r = requests.get(output_url, timeout=120)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Lipsync saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_assets(record_id: str, script: str) -> list[dict]:
    """
    Full 4-phase asset pipeline.

    Status flow:
      pending       → generating DALL-E 3 images
      images_done   → generating ElevenLabs audio
      audio_done    → generating Kling animated clips
      clips_done    → applying Kling lipsync
      lipsync_done  → ready for sync_assembler

    Returns the completed scene list.
    """
    _check_credentials()

    from tools.rewrite_script import parse_scenes

    scenes = parse_scenes(script)
    if not scenes:
        raise ValueError("No scenes found in script. Make sure the script uses [SCENE N] format.")

    assets_dir = Path("static") / "assets" / record_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[Asset Generator] {len(scenes)} scenes for record {record_id}")

    # -----------------------------------------------------------------------
    # Phase 1: DALL-E 3 images
    # -----------------------------------------------------------------------
    print("\n--- Phase 1: Generating images (DALL-E 3) ---")
    _set_status(record_id, "pending")

    for scene in scenes:
        n = scene["index"]
        img_path = assets_dir / f"scene_{n}.png"
        print(f"  Scene {n + 1}/{len(scenes)}: {scene['action'][:70]}...")
        if img_path.exists():
            print("    (cached)")
        else:
            generate_image(scene["action"], img_path)
        scene["image_path"] = str(img_path)
        _save_scene_data(record_id, scenes)

    _set_status(record_id, "images_done")
    print("Phase 1 complete.")

    # -----------------------------------------------------------------------
    # Phase 2: ElevenLabs audio
    # -----------------------------------------------------------------------
    print("\n--- Phase 2: Generating audio (ElevenLabs) ---")

    for scene in scenes:
        n = scene["index"]
        audio_path = assets_dir / f"audio_{n}.mp3"
        print(f"  Scene {n + 1}/{len(scenes)}")
        if audio_path.exists():
            print(f"    (cached)")
        else:
            generate_scene_audio(scene["dialogue"], audio_path)
        scene["audio_path"] = str(audio_path)
        _save_scene_data(record_id, scenes)

    _set_status(record_id, "audio_done")
    print("Phase 2 complete.")

    # -----------------------------------------------------------------------
    # Phase 3: Kling image-to-video
    # -----------------------------------------------------------------------
    print("\n--- Phase 3: Animating scenes (Kling i2v) ---")

    for scene in scenes:
        n = scene["index"]
        clip_path = assets_dir / f"clip_{n}.mp4"
        print(f"  Scene {n + 1}/{len(scenes)}")
        if clip_path.exists():
            print(f"    (cached)")
        else:
            generate_kling_clip(scene["image_path"], clip_path)
        scene["clip_path"] = str(clip_path)
        _save_scene_data(record_id, scenes)

    _set_status(record_id, "clips_done")
    print("Phase 3 complete.")

    # -----------------------------------------------------------------------
    # Phase 4: Kling lipsync
    # -----------------------------------------------------------------------
    print("\n--- Phase 4: Applying lipsync (Kling) ---")

    for scene in scenes:
        n = scene["index"]
        lipsync_path = assets_dir / f"lipsync_{n}.mp4"
        print(f"  Scene {n + 1}/{len(scenes)}")
        if lipsync_path.exists():
            print(f"    (cached)")
        else:
            apply_lipsync(scene["clip_path"], scene["audio_path"], lipsync_path)
        scene["lipsync_path"] = str(lipsync_path)
        _save_scene_data(record_id, scenes)

    _set_status(record_id, "lipsync_done")
    print("Phase 4 complete — all assets ready for assembly.")

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
