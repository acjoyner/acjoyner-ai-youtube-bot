"""
sync_assembler.py
-----------------
Assembles the final Finance-style YouTube video from per-scene assets.

Logic per scene:
  - Load the 5-second Kling animation clip.
  - Load the edge-tts audio for that scene's dialogue.
  - If audio_duration <= 5s: trim clip to audio_duration.
  - If audio_duration >  5s: play full 5s clip, then freeze the last frame
    for the remainder (exactly matching the CapCut "freeze last frame" technique
    described in the reference video).
  - Combine scene video + scene audio.

Then:
  - Concatenate all scenes end-to-end.
  - Mix in royalty-free background music at 10% volume.
  - Export to output_path via MoviePy (H.264 / AAC).
"""

import os
import json
import requests
import numpy as np
from pathlib import Path
from moviepy import (
    VideoFileClip, ImageClip, AudioFileClip,
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
# Per-scene assembly
# ---------------------------------------------------------------------------

def _build_scene_clip(clip_path: str, audio_path: str) -> VideoFileClip:
    """
    Combine one 5s Kling clip with its scene audio.
    Freeze-last-frame if the audio runs longer than the clip.
    """
    video = VideoFileClip(str(clip_path)).without_audio().resized((W, H)).with_fps(FPS)
    clip_dur = video.duration or 5.0

    if os.path.exists(audio_path):
        audio = AudioFileClip(str(audio_path))
        audio_dur = audio.duration or clip_dur
    else:
        audio     = silence(clip_dur)
        audio_dur = clip_dur

    if audio_dur <= clip_dur:
        # Trim the clip down to match the short audio
        scene_video = video.subclipped(0, audio_dur)
        scene_audio = audio

    else:
        # Audio is longer than the 5s clip — freeze last frame for remainder
        remainder = audio_dur - clip_dur
        last_frame = video.get_frame(clip_dur - 0.05)
        freeze     = ImageClip(last_frame).with_duration(remainder).with_fps(FPS)
        scene_video = concatenate_videoclips([video, freeze], method="compose")
        scene_audio = audio

    return scene_video.with_audio(scene_audio)


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def assemble_finance_video(
    scene_data: list[dict],
    output_path: str,
    tmp_dir: Path = Path(".tmp/finance_assembly"),
    music_volume: float = 0.10,
) -> str:
    """
    Assemble the full Finance video from scene_data.

    Args:
        scene_data:   List of scene dicts (from automated_asset_generator).
                      Each dict must have 'clip_path' and 'audio_path'.
        output_path:  Destination MP4 path.
        tmp_dir:      Scratch directory for music download.
        music_volume: Background music level (0.0–1.0). Default 10%.

    Returns:
        output_path on success.
    """
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    if not scene_data:
        raise ValueError("scene_data is empty — no scenes to assemble.")

    # Validate that all assets exist
    missing = []
    for s in scene_data:
        if not s.get("clip_path") or not Path(s["clip_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} clip: {s.get('clip_path')}")
        if not s.get("audio_path") or not Path(s["audio_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} audio: {s.get('audio_path')}")
    if missing:
        raise FileNotFoundError("Missing assets:\n" + "\n".join(missing))

    # Build each scene clip
    scene_clips = []
    for i, scene in enumerate(scene_data):
        print(f"  Assembling scene {i + 1}/{len(scene_data)}...")
        clip = _build_scene_clip(scene["clip_path"], scene["audio_path"])
        scene_clips.append(clip)

    # Concatenate all scenes
    print("  Concatenating scenes...")
    final = concatenate_videoclips(scene_clips, method="compose")

    # Background music
    music_path = _fetch_music(tmp_dir)
    if music_path:
        print("  Mixing in background music...")
        final = _add_music(final, music_path, volume=music_volume)
    else:
        print("  (No music — continuing without)")

    # Export
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    print(f"  Rendering to {output_path}...")
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
