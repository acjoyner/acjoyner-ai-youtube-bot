"""
build_workout_video.py
----------------------
Builds a complete follow-along dumbbell workout video.

Structure per exercise:
  - 40s WORK: stock footage + exercise name + countdown timer + 5-4-3-2-1 warning
  - 20s REST: green screen + "REST" + next exercise preview + countdown

Optional 60s section break between upper/lower body.
Background music: royalty-free hip-hop from Free Music Archive.
Voiceover: Microsoft edge-tts (free).

Usage:
  python build_workout_video.py workout.json output.mp4

workout.json format:
{
  "title": "Full Body Dumbbell Workout",
  "sections": [
    {"name": "Upper Body", "exercises": ["Bicep Curls", "Shoulder Press", ...]},
    {"name": "Lower Body", "exercises": ["Squats", "Lunges", ...]}
  ],
  "work_duration": 40,
  "rest_duration": 20,
  "section_rest": 60
}
"""

import os
import sys
import json
import asyncio
import tempfile
import requests
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip,
    ColorClip, concatenate_videoclips, AudioFileClip,
    CompositeAudioClip
)
from moviepy.audio.AudioClip import AudioArrayClip
from dotenv import load_dotenv

load_dotenv()

PEXELS_KEY = os.getenv("PIXEL_API")
W, H = 1920, 1080
FPS = 30

# --- Font helpers ---

def get_font(size: int):
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def text_image(text: str, font_size: int, color: tuple, bg_color=None,
               size=(W, H), position="center", alpha=255) -> np.ndarray:
    """Render text onto a transparent (or solid) RGBA canvas."""
    img = Image.new("RGBA", size, bg_color if bg_color else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if position == "center":
        x, y = (size[0] - tw) // 2, (size[1] - th) // 2
    elif position == "top":
        x, y = (size[0] - tw) // 2, int(size[1] * 0.08)
    elif position == "bottom":
        x, y = (size[0] - tw) // 2, int(size[1] * 0.82)
    elif isinstance(position, tuple):
        x, y = position
    else:
        x, y = (size[0] - tw) // 2, (size[1] - th) // 2
    draw.text((x, y), text, font=font, fill=(*color, alpha))
    return np.array(img)


# --- Pexels video fetcher ---

def fetch_exercise_clip(exercise: str, dest_dir: Path) -> Path:
    """Download a Pexels video for the given exercise. Returns local path."""
    safe = exercise.lower().replace(" ", "_").replace("/", "_")
    dest = dest_dir / f"{safe}.mp4"
    if dest.exists():
        return dest

    headers = {"Authorization": PEXELS_KEY}
    params = {"query": f"{exercise} dumbbell workout exercise", "per_page": 5, "size": "medium"}
    r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("videos"):
        # Fallback: broader search
        params["query"] = f"{exercise} workout"
        r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

    if not data.get("videos"):
        raise RuntimeError(f"No Pexels video found for: {exercise}")

    # Pick best resolution ≤ 1920px wide
    video = data["videos"][0]
    files = sorted(video["video_files"], key=lambda x: x.get("width", 0), reverse=True)
    url = next((f["link"] for f in files if f.get("width", 0) <= 1920), files[0]["link"])

    print(f"  Downloading: {exercise}")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    return dest


# --- Voiceover ---

async def _tts(text: str, path: str):
    try:
        import edge_tts
        voice = "en-US-GuyNeural"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(path)
    except ImportError:
        # Silently skip if edge-tts not installed
        pass


def make_voiceover(text: str, path: str):
    asyncio.run(_tts(text, path))


def silence(duration: float) -> AudioArrayClip:
    """Return a silent audio clip of given duration."""
    samples = int(44100 * duration)
    arr = np.zeros((samples, 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=44100)


# --- Video segment builders ---

def make_exercise_segment(exercise: str, video_path: Path,
                          duration: int, tmp_dir: Path) -> VideoFileClip:
    """40-second work segment with stock footage + overlays."""
    base = VideoFileClip(str(video_path)).without_audio()

    # Loop/trim to exact duration
    if base.duration < duration:
        loops = int(duration / base.duration) + 1
        from moviepy.editor import concatenate_videoclips
        base = concatenate_videoclips([base] * loops)
    base = base.subclip(0, duration).resize((W, H))

    # Dark overlay for readability
    dark = ColorClip((W, H), color=(0, 0, 0), duration=duration).set_opacity(0.45)

    # Exercise name (top center)
    name_arr = text_image(exercise.upper(), 72, (255, 255, 255), position="top")
    name_clip = ImageClip(name_arr, ismask=False).set_duration(duration)

    # WORK badge (top left)
    work_arr = text_image("WORK", 40, (255, 255, 255),
                          bg_color=(220, 50, 50, 200), size=(160, 60), position="center")
    work_clip = ImageClip(work_arr).set_duration(duration).set_position((40, 40))

    # Per-second countdown clips
    countdown_clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        is_warn = sec <= 5
        color = (255, 60, 60) if is_warn else (255, 255, 255)
        font_size = 160 if is_warn else 130
        arr = text_image(str(sec), font_size, color, position="bottom")
        clip = ImageClip(arr).set_start(t_start).set_duration(1)
        countdown_clips.append(clip)

    # Voiceover: "Starting [exercise]"
    vo_path = str(tmp_dir / f"vo_{exercise.replace(' ', '_')}_start.mp3")
    make_voiceover(f"Starting {exercise}", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad = silence(max(0, duration - audio.duration))
    from moviepy.editor import concatenate_audioclips
    full_audio = concatenate_audioclips([audio, pad]).subclip(0, duration)

    composite = CompositeVideoClip([base, dark, name_clip, work_clip] + countdown_clips)
    return composite.set_audio(full_audio)


def make_rest_segment(next_exercise: str, duration: int, tmp_dir: Path) -> ImageClip:
    """20-second rest screen."""
    clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        # Background
        bg = np.zeros((H, W, 3), dtype=np.uint8)
        bg[:] = (15, 30, 15)
        bg_clip = ImageClip(bg).set_start(t_start).set_duration(1)

        # REST text
        rest_arr = text_image("REST", 160, (76, 200, 76), position=(
            (W - 400) // 2, int(H * 0.15)
        ))
        rest_clip = ImageClip(rest_arr).set_start(t_start).set_duration(1)

        # Next exercise
        next_arr = text_image(f"Next: {next_exercise.upper()}", 52, (180, 180, 180),
                              position=((W - 900) // 2, int(H * 0.5)))
        next_clip = ImageClip(next_arr).set_start(t_start).set_duration(1)

        # Countdown
        count_arr = text_image(str(sec), 100, (255, 255, 255), position="bottom")
        count_clip = ImageClip(count_arr).set_start(t_start).set_duration(1)

        clips.extend([bg_clip, rest_clip, next_clip, count_clip])

    # Voiceover
    vo_path = str(tmp_dir / f"vo_rest_{next_exercise.replace(' ', '_')}.mp3")
    make_voiceover(f"Rest. Next up, {next_exercise}", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad = silence(max(0, duration - audio.duration))
    from moviepy.editor import concatenate_audioclips
    full_audio = concatenate_audioclips([audio, pad]).subclip(0, duration)

    composite = CompositeVideoClip(clips, size=(W, H)).set_duration(duration)
    return composite.set_audio(full_audio)


def make_section_break(section_name: str, duration: int, tmp_dir: Path) -> CompositeVideoClip:
    """60-second break between sections."""
    clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        bg = np.zeros((H, W, 3), dtype=np.uint8)
        bg[:] = (10, 10, 30)
        bg_clip = ImageClip(bg).set_start(t_start).set_duration(1)

        title_arr = text_image("Great Work!", 100, (255, 215, 0),
                               position=((W - 700) // 2, int(H * 0.2)))
        title_clip = ImageClip(title_arr).set_start(t_start).set_duration(1)

        next_arr = text_image(f"Starting {section_name.upper()}", 60, (255, 255, 255),
                              position=((W - 900) // 2, int(H * 0.42)))
        next_clip = ImageClip(next_arr).set_start(t_start).set_duration(1)

        in_arr = text_image(f"in {sec} seconds", 50, (160, 160, 160),
                            position=((W - 600) // 2, int(H * 0.56)))
        in_clip = ImageClip(in_arr).set_start(t_start).set_duration(1)

        clips.extend([bg_clip, title_clip, next_clip, in_clip])

    vo_path = str(tmp_dir / f"vo_break_{section_name.replace(' ', '_')}.mp3")
    make_voiceover(f"Great work! Get ready for {section_name}.", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad = silence(max(0, duration - audio.duration))
    from moviepy.editor import concatenate_audioclips
    full_audio = concatenate_audioclips([audio, pad]).subclip(0, duration)

    composite = CompositeVideoClip(clips, size=(W, H)).set_duration(duration)
    return composite.set_audio(full_audio)


def make_intro(title: str, duration: int = 5) -> CompositeVideoClip:
    """Simple 5-second intro card."""
    bg = np.zeros((H, W, 3), dtype=np.uint8)
    bg[:] = (10, 10, 30)
    bg_clip = ImageClip(bg).set_duration(duration)
    title_arr = text_image(title.upper(), 80, (255, 255, 255))
    title_clip = ImageClip(title_arr).set_duration(duration)
    return CompositeVideoClip([bg_clip, title_clip]).set_duration(duration)


# --- Music ---

def fetch_music(tmp_dir: Path) -> str | None:
    """
    Download royalty-free uptempo hip-hop from Free Music Archive (FMA).
    These tracks are CC-licensed and safe for YouTube.
    Returns local path or None if download fails.
    """
    tracks = [
        # Free Music Archive - CC0 / CC-BY hip-hop instrumentals
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Broke_For_Free/Directionless_EP/Broke_For_Free_-_01_-_Night_Owl.mp3",
        "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/ccCommunity/Kai_Engel/Sustains/Kai_Engel_-_09_-_Downfall.mp3",
    ]
    dest = tmp_dir / "background_music.mp3"
    if dest.exists():
        return str(dest)
    for url in tracks:
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


def add_background_music(video, music_path: str, volume: float = 0.12):
    """Loop music under the video at low volume."""
    music = AudioFileClip(music_path)
    # Loop music to match video length
    loops = int(video.duration / music.duration) + 2
    from moviepy.editor import concatenate_audioclips
    looped = concatenate_audioclips([music] * loops).subclip(0, video.duration)
    looped = looped.volumex(volume)

    if video.audio:
        mixed = CompositeAudioClip([video.audio, looped])
        return video.set_audio(mixed)
    return video.set_audio(looped)


# --- Main builder ---

def build_workout_video(plan: dict, output_path: str):
    """
    Build the full workout video from a plan dict.
    Saves final MP4 to output_path.
    """
    title = plan.get("title", "Dumbbell Workout")
    sections = plan["sections"]
    work_dur = plan.get("work_duration", 40)
    rest_dur = plan.get("rest_duration", 20)
    section_rest = plan.get("section_rest", 60)

    tmp_dir = Path(".tmp") / f"workout_{Path(output_path).stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    downloads = tmp_dir / "downloads"
    downloads.mkdir(exist_ok=True)

    all_clips = []

    # Intro
    print("Building intro...")
    all_clips.append(make_intro(title))

    for s_idx, section in enumerate(sections):
        section_name = section["name"]
        exercises = section["exercises"]

        print(f"\n--- Section: {section_name} ---")

        for e_idx, exercise in enumerate(exercises):
            print(f"  [{e_idx + 1}/{len(exercises)}] {exercise}")

            # Fetch stock video
            video_path = fetch_exercise_clip(exercise, downloads)

            # Work segment
            work_clip = make_exercise_segment(exercise, video_path, work_dur, tmp_dir)
            all_clips.append(work_clip)

            # Rest segment (skip after last exercise in last section)
            is_last = (s_idx == len(sections) - 1) and (e_idx == len(exercises) - 1)
            if not is_last:
                if e_idx < len(exercises) - 1:
                    next_ex = exercises[e_idx + 1]
                elif s_idx < len(sections) - 1:
                    next_ex = sections[s_idx + 1]["exercises"][0]
                else:
                    next_ex = "Done!"
                rest_clip = make_rest_segment(next_ex, rest_dur, tmp_dir)
                all_clips.append(rest_clip)

        # Section break (between sections, not after last)
        if s_idx < len(sections) - 1:
            next_section = sections[s_idx + 1]["name"]
            print(f"  Section break → {next_section}")
            break_clip = make_section_break(next_section, section_rest, tmp_dir)
            all_clips.append(break_clip)

    # Final card
    print("\nBuilding outro...")
    all_clips.append(make_intro("Great Work! Subscribe for More!"))

    # Concatenate all clips
    print("\nConcatenating clips...")
    final = concatenate_videoclips(all_clips, method="compose")

    # Add background music
    music_path = fetch_music(tmp_dir)
    if music_path:
        print("Adding background music...")
        final = add_background_music(final, music_path, volume=0.12)
    else:
        print("  (No music — download failed, continuing without)")

    # Export
    print(f"\nExporting to {output_path}...")
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        logger="bar"
    )
    print(f"\nDone: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python build_workout_video.py workout.json output.mp4")
        print("\nExample workout.json:")
        example = {
            "title": "Full Body Dumbbell Workout",
            "sections": [
                {"name": "Upper Body", "exercises": ["Bicep Curls", "Shoulder Press", "Chest Fly", "Tricep Extensions"]},
                {"name": "Lower Body", "exercises": ["Squats", "Lunges", "Romanian Deadlift", "Calf Raises"]}
            ],
            "work_duration": 40,
            "rest_duration": 20,
            "section_rest": 60
        }
        print(json.dumps(example, indent=2))
        sys.exit(1)

    with open(sys.argv[1]) as f:
        plan = json.load(f)
    build_workout_video(plan, sys.argv[2])
