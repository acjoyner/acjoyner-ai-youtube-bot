"""
generate_exercise_prompts.py
-----------------------------
Generates ChatGPT + NanoBanana image prompts for each exercise,
featuring the cartoon mascot in full body exercise poses.

Output:
  - One image prompt per exercise (for ChatGPT/NanoBanana)
  - One Meta AI animation prompt per exercise
  - Instructions for naming and saving clips

Usage:
  python generate_exercise_prompts.py "Bicep Curls,Shoulder Press,Squats"
"""

import sys
import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

CHARACTER_STYLE = """
The character is a cartoon mascot in the Family Guy-inspired style:
- Flat colors, thick outlines, simple shading
- Full body shown — head to toe, no cropping
- Athletic wear (fitted workout shirt, shorts or joggers, sneakers)
- Same art style: clean vector look, bold outlines, flat colors
- White or simple flat background
- Centered composition, full body visible
"""

SYSTEM_PROMPT = f"""You are a visual prompt engineer for a faceless fitness YouTube channel.
The channel uses a cartoon mascot character with this style:
{CHARACTER_STYLE}

For each exercise, generate:
1. An IMAGE PROMPT for ChatGPT/NanoBanana — one sentence describing the mascot performing that exercise, full body, proper form, dynamic pose
2. A META AI ANIMATION PROMPT — one sentence describing a subtle 5-second motion from that image

Rules:
- Always show the FULL BODY — never cropped
- Use correct exercise form in the description
- Keep poses dynamic and energetic
- Reference the character style in every prompt

Format each exercise as:
Exercise: [name]
Image prompt: [one sentence]
Animation prompt: [one sentence]
Clip filename: [exercise_name_no_spaces.mp4]
"""


def generate_exercise_prompts(exercises: list[str], niche: str = "fitness") -> str:
    exercise_list = "\n".join(f"- {e}" for e in exercises)

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Generate image and animation prompts for these exercises:\n{exercise_list}"
        }]
    )

    result = message.content[0].text.strip()

    # Add instructions header
    instructions = f"""
# Exercise Image & Animation Prompts
# Generated for {len(exercises)} exercises

## How to use:
1. Open ChatGPT + attach your mascot reference image
2. For each exercise below, paste the Image prompt
3. Generate the image, then take it to Meta AI
4. Paste the Animation prompt in Meta AI → generate 5-sec clip
5. Save each clip to: clips/exercises/<clip filename>
6. The workout builder will automatically use your clips

---

{result}

---

## After saving all clips:
- Go to the dashboard
- Add your workout
- Click Build Video — it will use your cartoon clips automatically
"""
    return instructions


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python generate_exercise_prompts.py "Exercise 1,Exercise 2,..."')
        sys.exit(1)

    exercises = [e.strip() for e in sys.argv[1].split(",") if e.strip()]
    result = generate_exercise_prompts(exercises)
    print(result)
