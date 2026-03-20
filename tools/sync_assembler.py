"""
sync_assembler.py
-----------------
Assembles the final Finance video from per-scene lipsync clips.

Each scene:
  - Loads the lipsync MP4 (Kling-animated, lip-synced to ElevenLabs audio).
  - If the audio is longer than the video clip, the last frame is frozen
    to cover the remainder — ensuring audio always plays fully.

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
# Per-scene assembly — lipsync clip + freeze-frame fallback
# ---------------------------------------------------------------------------

def _build_scene_clip(lipsync_path: str, audio_path: str) -> object:
    """
    Load the lipsync video clip.

    If audio is longer than the video (can happen if lipsync truncated),
    freeze the last frame for the remaining duration so the audio plays
    completely without a black screen.
    """
    video = VideoFileClip(lipsync_path).resized((W, H))
    audio = AudioFileClip(audio_path) if os.path.exists(audio_path) else silence(video.duration)

    vid_dur = video.duration or 0
    aud_dur = audio.duration or vid_dur

    if aud_dur <= vid_dur:
        # Audio fits — trim video to audio length
        clip = video.subclipped(0, aud_dur).with_audio(audio)
    else:
        # Audio is longer — freeze last frame to fill the gap
        last_t = max(0, vid_dur - 1 / FPS)
        last_frame = video.get_frame(last_t)
        freeze_dur = aud_dur - vid_dur
        freeze = ImageClip(last_frame).with_duration(freeze_dur).with_fps(FPS)
        clip = concatenate_videoclips([video, freeze]).with_audio(audio)

    return clip


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
                      Each dict must have 'lipsync_path' and 'audio_path'.
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
        if not s.get("lipsync_path") or not Path(s["lipsync_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} lipsync: {s.get('lipsync_path')}")
        if not s.get("audio_path") or not Path(s["audio_path"]).exists():
            missing.append(f"Scene {s.get('index', '?')} audio: {s.get('audio_path')}")
    if missing:
        raise FileNotFoundError("Missing assets:\n" + "\n".join(missing))

    # Build each scene
    scene_clips = []
    for i, scene in enumerate(scene_data):
        print(f"  Building scene {i + 1}/{len(scene_data)}...")
        clip = _build_scene_clip(scene["lipsync_path"], scene["audio_path"])
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
