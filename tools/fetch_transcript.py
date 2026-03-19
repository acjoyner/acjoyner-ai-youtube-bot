"""
fetch_transcript.py
-------------------
Given a YouTube video URL, fetches the transcript and returns plain text.
Uses youtube-transcript-api (free, no API key required).
"""

import sys
import re
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from URL: {url}")


def fetch_transcript(youtube_url: str) -> str:
    """Fetch transcript from a YouTube video URL. Returns plain text."""
    video_id = extract_video_id(youtube_url)
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    text = " ".join(entry.text for entry in transcript)
    # Clean up line breaks and extra spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_transcript.py <youtube_url>")
        sys.exit(1)
    url = sys.argv[1]
    result = fetch_transcript(url)
    print(result)
