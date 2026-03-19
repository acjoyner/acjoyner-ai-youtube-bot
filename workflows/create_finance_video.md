# Workflow: Create Finance YouTube Video

## Objective
Produce a short-form AI-generated finance video using a consistent cartoon mascot character, AI-generated visuals, AI voiceover, and CapCut editing.

## Reference
- Inspiration channel: Nick Invests style
- Example video: https://www.youtube.com/watch?v=zqtByiGjHPA
- Community: https://tuberversity.com/

---

## Required Inputs
- [ ] A finance video transcript (source: popular finance/fitness YouTube videos)
- [ ] Character attributes for the mascot (if creating a new one)
- [ ] Character reference image (for visual consistency)

---

## Step 1: Get the Script

**Source:** Take the transcript from a popular finance or fitness YouTube video and rewrite it as a 100% original version.

**How:**
1. Pull the transcript from YouTube (use the transcript feature under the video)
2. Paste into ChatGPT with this prompt:
   > "Rewrite this script as a 100% original version that covers the same topic and ideas but uses entirely different wording, structure, and phrasing. It should feel fresh and be completely mine."
3. Save the final script — you'll use it in Steps 3 and 4.

---

## Step 2: Generate the Character Image (if needed)

**Tool:** ChatGPT (image generation) or NanoBanana
**Only needed when:** Creating a new character or updating the mascot

**Prompt template:**
```
Use the attached image as the EXACT visual style reference for this character.
Your job is to recreate the SAME cartoon art style, line weight, proportions,
and facial structure but with the character details I provide below.

DO NOT invent a new style. MATCH the reference image exactly in:
- Head shape and body proportions
- Outline thickness and eye/mouth style
- Shading style (flat colors, thick outlines)
- Overall "Family Guy–inspired finance mascot" look

Character Attributes:
- Gender: [fill in]
- Age range: [fill in]
- Race / ethnicity: [fill in]
- Hairstyle: [fill in]
- Outfit: [fill in]
- Glasses: [fill in]
- Expression: [fill in]
- Face features: [fill in]

Pose: Full body, front-facing
Background: Simple flat white
Output: Clean mascot, high resolution, centered, 16:9 safe
```

**Output:** Save the character image — you'll use it in Step 3 for scene generation.

---

## Step 3: Generate Scene Images

**Tool:** ChatGPT (NanoBanana style)
**Input:** The script from Step 1 + character image from Step 2

**How:**
1. Read through the script section by section
2. Use the visuals prompt below to generate one image per sentence/idea (skip fillers)

**Visuals prompt:**
```
You are an AI visual prompt engineer.
Read the script below section by section and generate a sequence of
simple one-sentence image prompts — one prompt for every sentence or idea
(skip fillers and transitions).

Rules:
- Clean, bold outlines, simple shading
- Each prompt is one sentence
- Output in chronological order
- Format each entry as:
  [Script line]: ...
  Image prompt: ...
  Micro-animation prompt: ...
```

3. Paste each image prompt into ChatGPT to generate the scene images
4. Save all images in order (name them 001, 002, 003... to match script sequence)

---

## Step 4: Generate Voiceover Audio

**Tool:** Google AI Studio (free) or ElevenLabs (Dan voice, paid)

**Google AI Studio (free option):**
1. Go to Google AI Studio → Text to Speech
2. Select "Single speaker" audio option
3. Choose a voice that matches the character's personality
4. Paste the script from Step 1
5. Run it — listen and adjust until it sounds right
6. Download the audio file

**ElevenLabs (paid option):**
- Use the "Dan" voice for a finance/professional tone

---

## Step 5: Generate Videos from Images

**Tool:** Meta AI (meta.ai) — free

**How:**
1. Go to meta.ai and click **Video**
2. Upload a scene image (from Step 3)
3. Paste the same image prompt that ChatGPT used to generate that image
4. Generate — Meta AI produces a ~5 second video clip
5. **Freeze the last frame** of each video clip (done in CapCut, Step 6)
6. Repeat for every image in sequence

---

## Step 6: Edit and Assemble in CapCut

**Tool:** CapCut (free)

**How:**
1. Import all video clips in order (001, 002, 003...)
2. For each clip: freeze the last frame
3. Drop the voiceover audio from Step 4 onto the timeline
4. Sync clips to audio pacing — trim or extend frozen frames as needed
5. Review full video end to end
6. Export when finished

---

## Step 7: Test and Publish

1. Watch the exported video in full
2. Check audio/visual sync
3. Upload to YouTube with an optimized title and thumbnail
4. Share community link: https://tuberversity.com/

---

## Video Idea Generation (when you need new topics)

**Tool:** ChatGPT

**Prompt:**
```
Generate 30 original, highly clickable finance video ideas.
Each idea should:
- Be unique and feel fresh
- Appeal to mainstream viewers
- Be suitable for a short-form educational finance channel
```

---

## Edge Cases & Notes

- **Out of image credits:** Use NanoBanana or switch to a different ChatGPT session; Meta AI video is free with no credit limit currently
- **Audio doesn't sound right:** Adjust speed/pitch in Google AI Studio before downloading; re-run with a different voice if needed
- **Video clip too short/long:** Use the freeze-last-frame technique in CapCut to extend any clip to match audio
- **Script feels too similar to source:** Run it through ChatGPT again with "make this 20% more conversational and original"

---

## Tools Summary

| Step | Tool | Cost |
|------|------|------|
| Script rewriting | ChatGPT | Free |
| Character image | ChatGPT / NanoBanana | Free (limited credits) |
| Scene images | ChatGPT | Free (limited) |
| Video generation | Meta AI | Free |
| Voiceover | Google AI Studio | Free |
| Voiceover (alt) | ElevenLabs (Dan) | Paid |
| Editing | CapCut | Free |
