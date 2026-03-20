"""
automated_asset_generator.py
-----------------------------
Generates all visual assets for a Finance video automatically:

  1. Parses the structured scene script from the DB.
  2. Builds a DALL-E 3 image prompt from the Master Character Descriptor (MCD)
     + the scene ACTION — ensuring mascot consistency across every scene.
  3. Sends each prompt to OpenAI DALL-E 3 → downloads image locally to:
       static/assets/<record_id>/scene_<n>.png
  4. Generates per-scene TTS audio (edge-tts) for the DIALOGUE:
       static/assets/<record_id>/audio_<n>.mp3
  5. Saves the completed scene_data JSON array back to the DB.
  6. Updates auto_prod_status at each phase so the dashboard can show progress.

The sync_assembler then applies a Ken Burns (slow zoom) effect to each
still image, timed to its audio duration — no video clip generation needed.

Required .env keys:
  OPENAI_API_KEY   — OpenAI API key (for DALL-E 3, ~$0.04/image)
"""

import os
import sys
import json
import asyncio
import sqlite3
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_FILE    = os.getenv("DB_FILE", "youtube.db")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")


def _check_credentials():
    """Raise a clear error early if required API keys are missing."""
    if not OPENAI_KEY:
        raise EnvironmentError(
            "Missing OPENAI_API_KEY in .env — get yours at https://platform.openai.com/api-keys"
        )


# ---------------------------------------------------------------------------
# Master Character Descriptor — prepended to every DALL-E 3 prompt.
# Keeps the mascot visually consistent across all scenes without needing
# an expensive image-reference API.
# ---------------------------------------------------------------------------

MCD = (
    "A Family Guy-inspired cartoon of a Black male finance expert. "
    "He has a rounded afro, thin-rimmed gold glasses, a goatee, and a wide smile with white teeth. "
    "He is wearing a tailored navy blue business suit, a white dress shirt, and a gold-and-navy striped tie. "
    "Art style: Flat vector colors, thick bold black outlines, simple shading, "
    "centered full-body composition, high resolution, white background."
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


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
    Generate one scene image via DALL-E 3.
    Saves the PNG locally and returns the remote URL.
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

    r = requests.get(image_url, timeout=60)
    r.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)

    print(f"    Image saved: {output_path}")
    return image_url


# ---------------------------------------------------------------------------
# Per-scene TTS voiceover
# ---------------------------------------------------------------------------

async def _tts(text: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
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
    Asset generation pipeline — two phases:

      pending      → generating DALL-E 3 images
      images_done  → generating per-scene TTS audio
      audio_done   → ready for sync_assembler

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
    # Phase 1: Generate DALL-E 3 images
    # -----------------------------------------------------------------------
    print("\n--- Phase 1: Generating images (DALL-E 3) ---")
    _set_auto_prod_status(record_id, "pending")

    for scene in scenes:
        n = scene["index"]
        img_path = assets_dir / f"scene_{n}.png"
        print(f"  Scene {n + 1}/{len(scenes)}: {scene['action'][:70]}...")

        if img_path.exists():
            print(f"    (cached)")
        else:
            generate_image(scene["action"], img_path)

        scene["image_path"] = str(img_path)
        _save_scene_data(record_id, scenes)

    _set_auto_prod_status(record_id, "images_done")
    print("Phase 1 complete — all images generated.")

    # -----------------------------------------------------------------------
    # Phase 2: Generate per-scene TTS audio
    # -----------------------------------------------------------------------
    print("\n--- Phase 2: Generating audio (edge-tts) ---")

    for scene in scenes:
        n = scene["index"]
        audio_path = assets_dir / f"audio_{n}.mp3"
        print(f"  Scene {n + 1}/{len(scenes)}")

        if audio_path.exists():
            print(f"    Audio cached: {audio_path}")
        else:
            generate_scene_audio(scene["dialogue"], audio_path)

        scene["audio_path"] = str(audio_path)
        _save_scene_data(record_id, scenes)

    _set_auto_prod_status(record_id, "audio_done")
    print("Phase 2 complete — all audio generated.")

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
