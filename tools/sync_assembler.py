"""
sync_assembler.py
-----------------
Assembles the final Finance-style YouTube video from per-scene assets.

Each scene:
  - Loads the DALL-E 3 PNG for that scene.
  - Applies a slow Ken Burns zoom (4% over the audio duration) so the
    still image feels alive — identical to the "freeze last frame" technique
    described in the reference video, but generated automatically.
  - Layers the scene's edge-tts audio on top.

Then:
  - Concatenates all scenes end-to-end.
  - Mixes in royalty-free background music at 10% volume.
  - Exports to output_path via MoviePy (H.264 / AAC).
"""

import os
import json
import requests
import numpy as np
from pathlib import Path
from PIL import Image
from moviepy import (
    VideoClip, AudioFileClip,
    CompositeAudioClip, AudioArrayClip,
    concatenate_videoclips, concatenate_audioclips,
)
from dotenv import load_dotenv

load_dotenv()

W, H = 1920, 1080
FPS  = 30

MUSIC_TRACKS = [
    "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Broke_For_Free/Directionless_EP/Broke_For_Free_-_01_-_Night_Owl.mp3",
    "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/ccCommunity/Kai_Engel/Sustains/Kai_Engel_-_09_-_Downfall.mp3",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def silence(duration: float) -> AudioArrayClip:
    samples = max(1, int(44100 * duration))
    arr = np.zeros((samples, 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=44100)


def _fetch_music(tmp_dir: Path) -> str | None:
    dest = tmp_dir / "bg_music.mp3"
    if dest.exists():
        return str(dest)
    for url in MUSIC_TRACKS:
        try:
            print("  Downloading background music...")
            r = requests.get(url, timeout=30, stream=True)
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                return str(dest)
        except Exception:
            continue
    return None


def _add_music(video, music_path: str, volume: float = 0.10):
    music = AudioFileClip(music_path)
    loops = int((video.duration or 0) / (music.duration or 1)) + 2
    looped = concatenate_audioclips([music] * loops).subclipped(0, video.duration or 1)
    looped = looped.with_volume_scaled(volume)
    if video.audio:
        mixed = CompositeAudioClip([video.audio, looped])
        return video.with_audio(mixed)
    return video.with_audio(looped)


# ---------------------------------------------------------------------------
# Ken Burns effect
# ---------------------------------------------------------------------------

def _make_ken_burns(image_path: str, duration: float, zoom: float = 0.04) -> VideoClip:
    """
    Slow zoom-in over `duration` seconds.

    zoom=0.04 means the image grows 4% from start to end — subtle enough
    to feel like motion without being distracting.
    """
    img = Image.open(image_path).convert("RGB").resize((W, H), Image.LANCZOS)
    img_arr = np.array(img)

    def make_frame(t: float) -> np.ndarray:
        scale = 1.0 + zoom * (t / max(duration, 0.001))
        new_w = int(W * scale)
        new_h = int(H * scale)
        scaled = Image.fromarray(img_arr).resize((new_w, new_h), Image.LANCZOS)
        # Crop back to target size from the center
        x1 = (new_w - W) // 2
        y1 = (new_h - H) // 2
        cropped = scaled.crop((x1, y1, x1 + W, y1 + H))
        return np.array(cropped)

    return VideoClip(make_frame, duration=duration).with_fps(FPS)


# ---------------------------------------------------------------------------
# Per-scene assembly
# ---------------------------------------------------------------------------

def _build_scene_clip(image_path: str, audio_path: str) -> VideoClip:
    """Ken Burns still + scene audio."""
    if os.path.exists(audio_path):
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration or 3.0
    else:
        audio    = silence(3.0)
        duration = 3.0

    video = _make_ken_burns(image_path, duration)
    return video.with_audio(audio)


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def assemble_finance_video(
    scene_data: list[dict],
    output_path: str,
    tmp_dir: str = ".tmp/finance_assembly",
    music_volume: float = 0.10,
) -> str:
    """
    Assemble the full Finance video from scene_data.

    Args:
        scene_data:   List of scene dicts from automated_asset_generator.
                      Each dict must have 'image_path' and 'audio_path'.
        output_path:  Destination MP4 path.
        tmp_dir:      Scratch directory for music download.
        music_volume: Background music level (0.0–1.0). Default 10%.

    Returns:
        output_path on success.
    """
    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)

    if not scene_data:
        raise ValueError("scene_data is empty — no scenes to assemble.")

    # Validate assets
    missing = []
    for s in scene_data:
        if not s.get("image_path") or not Path(s["image_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} image: {s.get('image_path')}")
        if not s.get("audio_path") or not Path(s["audio_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} audio: {s.get('audio_path')}")
    if missing:
        raise FileNotFoundError("Missing assets:\n" + "\n".join(missing))

    # Build each scene
    scene_clips = []
    for i, scene in enumerate(scene_data):
        print(f"  Building scene {i + 1}/{len(scene_data)}...")
        clip = _build_scene_clip(scene["image_path"], scene["audio_path"])
        scene_clips.append(clip)

    # Concatenate
    print("  Concatenating scenes...")
    final = concatenate_videoclips(scene_clips, method="compose")

    # Background music
    music_path = _fetch_music(tmp)
    if music_path:
        print("  Mixing in background music...")
        final = _add_music(final, music_path, volume=music_volume)
    else:
        print("  (No music — download failed, continuing without)")

    # Export
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    print(f"  Rendering to {output_path}  ({final.duration:.1f}s)...")
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        logger=None,
    )
    print(f"  Done: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys, sqlite3, os

    DB_FILE = os.getenv("DB_FILE", "youtube.db")

    if len(sys.argv) < 3:
        print("Usage: python sync_assembler.py <record_id> <output.mp4>")
        sys.exit(1)

    record_id   = sys.argv[1]
    output_path = sys.argv[2]

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT scene_data FROM Videos WHERE record_id = ?", (record_id,)).fetchone()
    conn.close()

    if not row or not row["scene_data"]:
        print("No scene_data found. Run automated_asset_generator.py first.")
        sys.exit(1)

    scenes = json.loads(row["scene_data"])
    assemble_finance_video(scenes, output_path)
