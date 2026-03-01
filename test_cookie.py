#!/usr/bin/env python3
import yt_dlp
from pathlib import Path

# Test cookies
cookies_path = Path(__file__).parent / "cookies.txt"
print(f"Testing cookies at: {cookies_path}")
print(f"File exists: {cookies_path.exists()}")

if cookies_path.exists():
    print(f"File size: {cookies_path.stat().st_size} bytes")
    print("\nFirst few lines:")
    with open(cookies_path, 'r') as f:
        for i, line in enumerate(f):
            if i < 5:
                print(f"  {line.strip()}")
            else:
                break

# Test YouTube extraction with cookies
test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
print(f"\nTesting extraction with cookies...")

ydl_opts = {
    'quiet': False,
    'cookiefile': str(cookies_path),
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(test_url, download=False)
        print(f" Success! Video title: {info.get('title', 'Unknown')}")
except Exception as e:
    print(f" Failed: {e}")