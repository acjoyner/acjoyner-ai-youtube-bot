"""
rewrite_script.py
-----------------
Takes a raw transcript and rewrites it as a 100% original script
using Claude, structured as numbered scenes.

Each scene contains:
  DIALOGUE: The spoken words for that scene (2-3 sentences max)
  ACTION:   A one-sentence visual description of what the mascot is doing
            — used directly as the scene action in DALL-E 3 image prompts.

The structured format is consumed by automated_asset_generator.py to
generate one DALL-E 3 image + one fal.ai video clip per scene.
"""

import sys
import os
import re
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an expert YouTube scriptwriter specializing in Finance, Fitness, and Tech/AI content.
Your job is to rewrite transcripts as 100% original scripts that cover the same topic and ideas
but use entirely different wording, structure, and phrasing.

Rules:
- The script must feel completely fresh and be 100% yours
- Keep the same educational value and key points
- Write in a conversational, engaging YouTube tone
- Keep sentences short and punchy — this is for video
- Do NOT start sentences with "I" repeatedly
- Add a strong hook in the first 2 sentences (Scene 1)
- End with a clear call to action (last scene)
- Finance scripts must include this disclaimer in the final scene: "This is for educational purposes only and is not financial advice."
- Tech/AI scripts should be accessible to mainstream viewers, not just developers
- Fitness scripts should be motivating and action-oriented

OUTPUT FORMAT — you MUST follow this exactly:

[SCENE 1]
DIALOGUE: "Spoken words for this scene. Keep it 2-3 sentences max."
ACTION: "One sentence describing what the cartoon mascot is doing — be specific and visual. E.g. 'Mascot stands confidently with arms crossed, a rising green stock chart visible on the wall behind them.'"

[SCENE 2]
DIALOGUE: "..."
ACTION: "..."

[SCENE 3]
...

Continue until the full script is covered. Aim for 8–15 scenes total.
Do NOT include anything outside the [SCENE N] blocks.
"""


MAX_TRANSCRIPT_CHARS = 20_000  # ~5k tokens — keeps us well within context limits


def rewrite_script(transcript: str, niche: str = "finance") -> str:
    """Rewrite a transcript as a structured scene-by-scene script."""
    # Truncate very long transcripts to avoid invalid_request_error (prompt_too_long)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]
        print(f"  [rewrite_script] Transcript truncated to {MAX_TRANSCRIPT_CHARS} chars.")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Niche: {niche}\n\nRewrite this transcript as a structured scene-by-scene YouTube script:\n\n{transcript}"
            }
        ]
    )
    return message.content[0].text.strip()


def parse_scenes(script: str) -> list[dict]:
    """
    Parse a structured script into a list of scene dicts.

    Returns:
        [{"index": 0, "dialogue": "...", "action": "..."}, ...]
    """
    scenes = []
    blocks = re.split(r'\[SCENE \d+\]', script)
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        dialogue_match = re.search(r'DIALOGUE:\s*"(.+?)"', block, re.DOTALL)
        action_match   = re.search(r'ACTION:\s*"(.+?)"',   block, re.DOTALL)
        if dialogue_match and action_match:
            scenes.append({
                "index":    len(scenes),
                "dialogue": dialogue_match.group(1).strip(),
                "action":   action_match.group(1).strip(),
                "image_url":  None,
                "clip_url":   None,
                "clip_path":  None,
                "audio_path": None,
            })
    return scenes


def script_to_plain_text(script: str) -> str:
    """Extract just the spoken dialogue from a structured script (for TTS / reading)."""
    scenes = parse_scenes(script)
    return "\n\n".join(s["dialogue"] for s in scenes)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rewrite_script.py <transcript_file> [niche]")
        sys.exit(1)
    with open(sys.argv[1], "r") as f:
        transcript = f.read()
    niche = sys.argv[2] if len(sys.argv) > 2 else "finance"
    result = rewrite_script(transcript, niche)
    print(result)
    print("\n--- Parsed scenes ---")
    for s in parse_scenes(result):
        print(f"Scene {s['index'] + 1}: {s['dialogue'][:60]}...")
