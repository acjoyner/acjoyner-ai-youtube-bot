"""
generate_voiceover.py
---------------------
Generates a voiceover MP3 from a script using Microsoft edge-tts (free).
No API key required. High quality neural voices.

Available voices (good options):
  en-US-GuyNeural       — Male, professional, warm
  en-US-AndrewNeural    — Male, casual, conversational
  en-US-ChristopherNeural — Male, authoritative
  en-US-JennyNeural     — Female, friendly
  en-US-AriaNeural      — Female, warm, expressive

Usage:
  python generate_voiceover.py <script_file> <output.mp3> [voice]
"""

import sys
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VOICES = {
    "male_warm":          "en-US-GuyNeural",
    "male_casual":        "en-US-AndrewNeural",
    "male_authoritative": "en-US-ChristopherNeural",
    "female_friendly":    "en-US-JennyNeural",
    "female_expressive":  "en-US-AriaNeural",
}

DEFAULT_VOICE = "en-US-GuyNeural"


async def _generate(text: str, output_path: str, voice: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_voiceover(script: str, output_path: str, voice: str = DEFAULT_VOICE) -> str:
    """
    Generate a voiceover MP3 from script text.
    Returns the output path.
    """
    os.makedirs(Path(output_path).parent, exist_ok=True)
    asyncio.run(_generate(script, output_path, voice))
    return output_path


def list_voices():
    """Print available voice options."""
    print("Available voices:")
    for name, voice_id in VOICES.items():
        marker = " (default)" if voice_id == DEFAULT_VOICE else ""
        print(f"  {name}: {voice_id}{marker}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python generate_voiceover.py <script_file> <output.mp3> [voice]")
        print()
        list_voices()
        sys.exit(1)

    with open(sys.argv[1], "r") as f:
        script = f.read().strip()

    voice = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE
    output = sys.argv[2]

    print(f"Generating voiceover with voice: {voice}")
    generate_voiceover(script, output, voice)
    print(f"Saved: {output}")
