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

Supports both landscape (1920x1080) and vertical Shorts (1080x1920) format.

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
from moviepy import (
    VideoFileClip, ImageClip, CompositeVideoClip,
    ColorClip, concatenate_videoclips, AudioFileClip,
    CompositeAudioClip, AudioArrayClip, concatenate_audioclips
)
from dotenv import load_dotenv

load_dotenv()

PEXELS_KEY = os.getenv("PIXEL_API")

# Default dimensions — overridden per-build via is_short flag
LANDSCAPE = (1920, 1080)
PORTRAIT  = (1080, 1920)
FPS = 30


# --- Progress logger ---

try:
    import proglog as _proglog

    class FileProgressLogger(_proglog.ProgressBarLogger):
        """Proglog-compatible logger that writes render % to a JSON file."""

        def __init__(self, progress_file: str):
            super().__init__()
            self.progress_file = progress_file
            self._last_pct = -1
            print(f"[FileProgressLogger] Initialized. Writing progress to: {progress_file}")

        def bars_callback(self, bar, attr, value, _old_value=None):
            print(f"[FileProgressLogger] bars_callback → bar={bar!r} attr={attr!r} value={value!r}", flush=True)
            if attr == "index":
                bar_info = self.bars.get(bar) or {}
                total = bar_info.get("total") or 0
                print(f"[FileProgressLogger]   bar_info={bar_info}  total={total}", flush=True)
                if total > 0:
                    pct = int(value / total * 100)
                    if pct != self._last_pct:
                        self._last_pct = pct
                        print(f"[FileProgressLogger] Writing {pct}% ({value}/{total}) to {self.progress_file}", flush=True)
                        try:
                            with open(self.progress_file, "w") as f:
                                json.dump({"pct": pct, "index": value, "total": total}, f)
                        except Exception as write_err:
                            print(f"[FileProgressLogger] ERROR writing progress file: {write_err}", flush=True)

        def callback(self, **kw):
            print(f"[FileProgressLogger] callback() kw={list(kw.keys())}", flush=True)

except ImportError:
    print("[FileProgressLogger] WARNING: proglog not installed — no render progress tracking")
    class FileProgressLogger:
        def __init__(self, progress_file: str):
            self.progress_file = progress_file
        def callback(self, **kw):
            pass


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
               w: int = 1920, h: int = 1080,
               position="center", alpha=255) -> np.ndarray:
    """Render text onto a transparent (or solid) RGBA canvas of size (w, h)."""
    img = Image.new("RGBA", (w, h), bg_color if bg_color else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if position == "center":
        x, y = (w - tw) // 2, (h - th) // 2
    elif position == "top":
        x, y = (w - tw) // 2, int(h * 0.08)
    elif position == "bottom":
        x, y = (w - tw) // 2, int(h * 0.82)
    elif isinstance(position, tuple):
        x, y = position
    else:
        x, y = (w - tw) // 2, (h - th) // 2
    draw.text((x, y), text, font=font, fill=(*color, alpha))
    return np.array(img)


def fit_clip_to_frame(clip, w: int, h: int) -> VideoFileClip:
    """
    Fit a video clip into (w, h) without distortion.
    - Landscape source → landscape target: simple resize/crop
    - Landscape source → portrait target (Shorts): center-crop to fill vertically
    """
    cw, ch = clip.size
    target_ratio = w / h
    source_ratio = cw / ch

    if abs(target_ratio - source_ratio) < 0.05:
        # Same ratio — just resize
        return clip.resized((w, h))

    if target_ratio < 1.0 and source_ratio > 1.0:
        # Portrait target, landscape source — crop center column
        scale = h / ch
        new_w = int(cw * scale)
        new_h = h
        scaled = clip.resized((new_w, new_h))
        x_center = new_w // 2
        x1 = x_center - w // 2
        return scaled.cropped(x1=x1, y1=0, x2=x1 + w, y2=new_h)

    # Default: resize to fill
    return clip.resized((w, h))


# --- Pexels video fetcher ---

CLIPS_DIR = Path("clips/exercises")


def fetch_exercise_clip(exercise: str, dest_dir: Path) -> Path:
    """
    Return a video clip for the given exercise.
    Priority:
      1. clips/exercises/<safe_name>.mp4  — user-provided clips
      2. .tmp/.../downloads/<safe_name>.mp4 — cached Pexels download
      3. Pexels API — download and cache
    """
    safe = exercise.lower().replace(" ", "_").replace("/", "_")

    local = CLIPS_DIR / f"{safe}.mp4"
    if local.exists():
        print(f"  Using local clip: {local}")
        return local

    dest = dest_dir / f"{safe}.mp4"
    if dest.exists():
        return dest

    if not PEXELS_KEY:
        raise RuntimeError(f"No local clip found for '{exercise}' and PIXEL_API not set.")

    headers = {"Authorization": PEXELS_KEY}
    params = {"query": f"{exercise} dumbbell workout exercise", "per_page": 5, "size": "medium"}
    r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not data.get("videos"):
        params["query"] = f"{exercise} workout"
        r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

    if not data.get("videos"):
        raise RuntimeError(f"No clip found for: {exercise}. Add one to clips/exercises/{safe}.mp4")

    video = data["videos"][0]
    files = sorted(video["video_files"], key=lambda x: x.get("width", 0), reverse=True)
    url = next((f["link"] for f in files if f.get("width", 0) <= 1920), files[0]["link"])

    print(f"  Downloading from Pexels: {exercise}")
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
        communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
        await communicate.save(path)
    except ImportError:
        pass


def make_voiceover(text: str, path: str):
    asyncio.run(_tts(text, path))


def silence(duration: float) -> AudioArrayClip:
    samples = int(44100 * duration)
    arr = np.zeros((samples, 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=44100)


# --- Video segment builders ---
# All builders accept w, h so they work correctly for both landscape and Shorts.

def make_exercise_segment(exercise: str, video_path: Path,
                          duration: int, tmp_dir: Path,
                          w: int, h: int) -> VideoFileClip:
    """Work segment: stock footage + overlays."""
    base = VideoFileClip(str(video_path)).without_audio()

    if (base.duration or 0) < duration:
        loops = int(duration / (base.duration or 1)) + 1
        base = concatenate_videoclips([base] * loops)
    base = base.subclipped(0, duration)
    base = fit_clip_to_frame(base, w, h)

    dark = ColorClip((w, h), color=(0, 0, 0), duration=duration).with_opacity(0.45)

    font_name  = 72  if w >= 1920 else 90   # larger font for Shorts (narrower but taller)
    font_count = 130 if w >= 1920 else 150
    font_warn  = 160 if w >= 1920 else 180

    name_arr  = text_image(exercise.upper(), font_name, (255, 255, 255), w=w, h=h, position="top")
    name_clip = ImageClip(name_arr).with_duration(duration)

    work_arr  = text_image("WORK", 40, (255, 255, 255),
                           bg_color=(220, 50, 50, 200), w=160, h=60, position="center")
    work_clip = ImageClip(work_arr).with_duration(duration).with_position((40, 40))

    countdown_clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        is_warn = sec <= 5
        color = (255, 60, 60) if is_warn else (255, 255, 255)
        fs = font_warn if is_warn else font_count
        arr  = text_image(str(sec), fs, color, w=w, h=h, position="bottom")
        clip = ImageClip(arr).with_start(t_start).with_duration(1)
        countdown_clips.append(clip)

    vo_path = str(tmp_dir / f"vo_{exercise.replace(' ', '_')}_start.mp3")
    make_voiceover(f"Starting {exercise}", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad   = silence(max(0, duration - (audio.duration or 0)))
    full_audio = concatenate_audioclips([audio, pad]).subclipped(0, duration)

    composite = CompositeVideoClip([base, dark, name_clip, work_clip] + countdown_clips)
    return composite.with_audio(full_audio)


def make_rest_segment(next_exercise: str, duration: int, tmp_dir: Path,
                      w: int, h: int) -> CompositeVideoClip:
    """Rest screen."""
    clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        bg_arr = np.zeros((h, w, 3), dtype=np.uint8)
        bg_arr[:] = (15, 30, 15)
        bg_clip = ImageClip(bg_arr).with_start(t_start).with_duration(1)

        rest_arr  = text_image("REST", 160, (76, 200, 76), w=w, h=h,
                               position=((w - 400) // 2, int(h * 0.15)))
        rest_clip = ImageClip(rest_arr).with_start(t_start).with_duration(1)

        next_arr  = text_image(f"Next: {next_exercise.upper()}", 52, (180, 180, 180), w=w, h=h,
                               position=((w - min(900, w - 40)) // 2, int(h * 0.5)))
        next_clip = ImageClip(next_arr).with_start(t_start).with_duration(1)

        count_arr  = text_image(str(sec), 100, (255, 255, 255), w=w, h=h, position="bottom")
        count_clip = ImageClip(count_arr).with_start(t_start).with_duration(1)

        clips.extend([bg_clip, rest_clip, next_clip, count_clip])

    vo_path = str(tmp_dir / f"vo_rest_{next_exercise.replace(' ', '_')}.mp3")
    make_voiceover(f"Rest. Next up, {next_exercise}", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad   = silence(max(0, duration - (audio.duration or 0)))
    full_audio = concatenate_audioclips([audio, pad]).subclipped(0, duration)

    composite = CompositeVideoClip(clips, size=(w, h)).with_duration(duration)
    return composite.with_audio(full_audio)


def make_section_break(section_name: str, duration: int, tmp_dir: Path,
                       w: int, h: int) -> CompositeVideoClip:
    """Section break between upper/lower body."""
    clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        bg_arr = np.zeros((h, w, 3), dtype=np.uint8)
        bg_arr[:] = (10, 10, 30)
        bg_clip = ImageClip(bg_arr).with_start(t_start).with_duration(1)

        title_arr = text_image("Great Work!", 100, (255, 215, 0), w=w, h=h,
                               position=((w - 700) // 2, int(h * 0.2)))
        title_clip = ImageClip(title_arr).with_start(t_start).with_duration(1)

        next_arr  = text_image(f"Starting {section_name.upper()}", 60, (255, 255, 255), w=w, h=h,
                               position=((w - min(900, w - 40)) // 2, int(h * 0.42)))
        next_clip = ImageClip(next_arr).with_start(t_start).with_duration(1)

        in_arr  = text_image(f"in {sec} seconds", 50, (160, 160, 160), w=w, h=h,
                             position=((w - 600) // 2, int(h * 0.56)))
        in_clip = ImageClip(in_arr).with_start(t_start).with_duration(1)

        clips.extend([bg_clip, title_clip, next_clip, in_clip])

    vo_path = str(tmp_dir / f"vo_break_{section_name.replace(' ', '_')}.mp3")
    make_voiceover(f"Great work! Get ready for {section_name}.", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad   = silence(max(0, duration - (audio.duration or 0)))
    full_audio = concatenate_audioclips([audio, pad]).subclipped(0, duration)

    composite = CompositeVideoClip(clips, size=(w, h)).with_duration(duration)
    return composite.with_audio(full_audio)


def make_round_break(round_num: int, total_rounds: int, duration: int, tmp_dir: Path,
                     w: int, h: int) -> CompositeVideoClip:
    """Break between rounds."""
    clips = []
    for sec in range(duration, 0, -1):
        t_start = duration - sec
        bg_arr = np.zeros((h, w, 3), dtype=np.uint8)
        bg_arr[:] = (20, 20, 20)
        bg_clip = ImageClip(bg_arr).with_start(t_start).with_duration(1)

        done_arr  = text_image(f"Round {round_num} Complete!", 90, (255, 215, 0), w=w, h=h,
                               position=((w - 800) // 2, int(h * 0.2)))
        done_clip = ImageClip(done_arr).with_start(t_start).with_duration(1)

        next_arr  = text_image(f"Round {round_num + 1} of {total_rounds}", 65, (255, 255, 255), w=w, h=h,
                               position=((w - 600) // 2, int(h * 0.42)))
        next_clip = ImageClip(next_arr).with_start(t_start).with_duration(1)

        in_arr  = text_image(f"starting in {sec}s", 48, (160, 160, 160), w=w, h=h,
                             position=((w - 500) // 2, int(h * 0.56)))
        in_clip = ImageClip(in_arr).with_start(t_start).with_duration(1)

        count_arr  = text_image(str(sec), 80, (255, 255, 255), w=w, h=h, position="bottom")
        count_clip = ImageClip(count_arr).with_start(t_start).with_duration(1)

        clips.extend([bg_clip, done_clip, next_clip, in_clip, count_clip])

    vo_path = str(tmp_dir / f"vo_round_{round_num}_break.mp3")
    make_voiceover(f"Round {round_num} complete. Get ready for round {round_num + 1}.", vo_path)
    audio = AudioFileClip(vo_path) if os.path.exists(vo_path) else silence(duration)
    pad   = silence(max(0, duration - (audio.duration or 0)))
    full_audio = concatenate_audioclips([audio, pad]).subclipped(0, duration)

    composite = CompositeVideoClip(clips, size=(w, h)).with_duration(duration)
    return composite.with_audio(full_audio)


def make_intro(title: str, duration: int = 5, w: int = 1920, h: int = 1080) -> CompositeVideoClip:
    """Simple 5-second intro/outro card."""
    bg_arr = np.zeros((h, w, 3), dtype=np.uint8)
    bg_arr[:] = (10, 10, 30)
    bg_clip    = ImageClip(bg_arr).with_duration(duration)
    title_arr  = text_image(title.upper(), 80, (255, 255, 255), w=w, h=h)
    title_clip = ImageClip(title_arr).with_duration(duration)
    return CompositeVideoClip([bg_clip, title_clip]).with_duration(duration)


# --- Music ---

def fetch_music(tmp_dir: Path) -> str | None:
    tracks = [
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
    music = AudioFileClip(music_path)
    loops = int((video.duration or 0) / (music.duration or 1)) + 2
    looped = concatenate_audioclips([music] * loops).subclipped(0, video.duration or 1)
    looped = looped.with_volume_scaled(volume)
    if video.audio:
        mixed = CompositeAudioClip([video.audio, looped])
        return video.with_audio(mixed)
    return video.with_audio(looped)


# --- Main builder ---

def build_workout_video(plan: dict, output_path: str, record_id: str = None, is_short: bool = False):
    """Build the full workout video. is_short=True produces 1080x1920 vertical format."""
    title         = plan.get("title", "Dumbbell Workout")
    sections      = plan["sections"]
    work_dur      = plan.get("work_duration", 40)
    rest_dur      = plan.get("rest_duration", 20)
    section_rest  = plan.get("section_rest", 60)
    global_rounds = plan.get("rounds", 1)
    round_rest    = plan.get("round_rest", 30)

    w, h = PORTRAIT if is_short else LANDSCAPE
    print(f"Format: {'Shorts (portrait)' if is_short else 'Landscape'} — {w}x{h}")

    tmp_dir   = Path(".tmp") / f"workout_{record_id or Path(output_path).stem}"
    downloads = tmp_dir / "downloads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(exist_ok=True)

    all_clips = []

    print("Building intro...")
    all_clips.append(make_intro(title, w=w, h=h))

    for s_idx, section in enumerate(sections):
        section_name  = section["name"]
        exercises     = section["exercises"]
        rounds        = section.get("rounds", global_rounds)
        is_last_section = (s_idx == len(sections) - 1)

        print(f"\n--- Section: {section_name} ({rounds} round{'s' if rounds > 1 else ''}) ---")

        for round_num in range(1, rounds + 1):
            if rounds > 1:
                print(f"  Round {round_num}/{rounds}")
            is_last_round = (round_num == rounds)

            for e_idx, exercise in enumerate(exercises):
                print(f"    [{e_idx + 1}/{len(exercises)}] {exercise}")
                video_path = fetch_exercise_clip(exercise, downloads)
                work_clip  = make_exercise_segment(exercise, video_path, work_dur, tmp_dir, w, h)
                all_clips.append(work_clip)

                is_last_exercise = (e_idx == len(exercises) - 1)
                is_very_last     = is_last_section and is_last_round and is_last_exercise

                if not is_very_last:
                    if not is_last_exercise:
                        next_ex = exercises[e_idx + 1]
                    elif not is_last_round:
                        next_ex = f"Round {round_num + 1} — {exercises[0]}"
                    elif not is_last_section:
                        next_ex = sections[s_idx + 1]["exercises"][0]
                    else:
                        next_ex = "Done!"
                    rest_clip = make_rest_segment(next_ex, rest_dur, tmp_dir, w, h)
                    all_clips.append(rest_clip)

            if not is_last_round:
                print(f"  Round break → Round {round_num + 1}")
                round_clip = make_round_break(round_num, rounds, round_rest, tmp_dir, w, h)
                all_clips.append(round_clip)

        if not is_last_section:
            next_section = sections[s_idx + 1]["name"]
            print(f"  Section break → {next_section}")
            break_clip = make_section_break(next_section, section_rest, tmp_dir, w, h)
            all_clips.append(break_clip)

    print("\nBuilding outro...")
    all_clips.append(make_intro("Great Work! Subscribe for More!", w=w, h=h))

    print("\nNormalising clips...")
    normed = [clip.resized((w, h)).with_fps(FPS) for clip in all_clips]

    print("Concatenating clips...")
    final = concatenate_videoclips(normed, method="compose")

    music_path = fetch_music(tmp_dir)
    if music_path:
        print("Adding background music...")
        final = add_background_music(final, music_path, volume=0.12)
    else:
        print("  (No music — download failed, continuing without)")

    print(f"\nExporting to {output_path}...")
    progress_file = str(tmp_dir / "progress.json")
    print(f"Progress file path: {os.path.abspath(progress_file)}")
    print(f"Final video: {final.duration:.1f}s  fps: {final.fps}  size: {final.size}")

    logger = FileProgressLogger(progress_file) if record_id else "bar"
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        logger=logger,
    )
    print(f"\nDone: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python build_workout_video.py workout.json output.mp4 [--short]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        plan = json.load(f)
    is_short = "--short" in sys.argv
    build_workout_video(plan, sys.argv[2], is_short=is_short)
