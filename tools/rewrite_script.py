"""
rewrite_script.py
-----------------
Takes a raw transcript and rewrites it as a 100% original script
using Claude. Covers the same topic but with entirely different
wording, structure, and phrasing.
"""

import sys
import os
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
- Add a strong hook in the first 2 sentences
- End with a clear call to action
- Do NOT include any stage directions, [PAUSE], or formatting markers
- Output ONLY the script text, nothing else
- Finance scripts must include this disclaimer at the end: "This is for educational purposes only and is not financial advice."
- Tech/AI scripts should be accessible to mainstream viewers, not just developers
- Fitness scripts should be motivating and action-oriented
"""


def rewrite_script(transcript: str, niche: str = "finance") -> str:
    """Rewrite a transcript as an original YouTube script."""
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Niche: {niche}\n\nRewrite this transcript as a 100% original YouTube script:\n\n{transcript}"
            }
        ]
    )
    return message.content[0].text.strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rewrite_script.py <transcript_file> [niche]")
        sys.exit(1)
    with open(sys.argv[1], "r") as f:
        transcript = f.read()
    niche = sys.argv[2] if len(sys.argv) > 2 else "finance"
    result = rewrite_script(transcript, niche)
    print(result)
