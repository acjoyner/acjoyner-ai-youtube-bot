"""
generate_visual_prompts.py
--------------------------
Takes a rewritten script and generates a production packet:
  - Image prompts (for ChatGPT + NanoBanana)
  - Micro-animation prompts (for Meta AI)
  - Clean voiceover script (for Google AI Studio or ElevenLabs)

Output is a formatted text file ready to work from top to bottom.
"""

import sys
import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an AI visual prompt engineer for a faceless YouTube channel.
The channel uses a cartoon mascot character (Family Guy-inspired style, flat colors, thick outlines).
There are three niches: Finance (mascot in navy suit), Fitness (mascot in athletic wear), Tech/AI (mascot in casual/hoodie).

Your job is to read a YouTube script and generate a production packet with three sections.

SECTION 1 - IMAGE PROMPTS (for ChatGPT + NanoBanana)
- One image prompt per sentence or idea (skip fillers and transitions)
- Each prompt must reference the mascot character naturally in the scene
- Use clean, bold outlines, flat colors, simple shading
- Format:
  [Script line]: <exact line from script>
  Image prompt: <one sentence describing the scene with the mascot>

SECTION 2 - MICRO-ANIMATION PROMPTS (for Meta AI video generation)
- One micro-animation prompt per scene (matches the image prompts above)
- Keep it to one sentence describing a subtle motion (5 seconds max)
- Format:
  Scene [N]: <one sentence micro-animation>

SECTION 3 - VOICEOVER SCRIPT (for Google AI Studio or ElevenLabs)
- The clean script with no formatting, stage directions, or markers
- Exactly as it should be read aloud
- One paragraph, natural speech flow

Output all three sections clearly labeled. Nothing else.
"""


def generate_visual_prompts(script: str, niche: str = "finance") -> str:
    """Generate full production packet from a script."""
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Niche: {niche}\n\nGenerate the production packet for this script:\n\n{script}"
            }
        ]
    )
    return message.content[0].text.strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_visual_prompts.py <script_file> [niche]")
        sys.exit(1)
    with open(sys.argv[1], "r") as f:
        script = f.read()
    niche = sys.argv[2] if len(sys.argv) > 2 else "finance"
    result = generate_visual_prompts(script, niche)
    print(result)
