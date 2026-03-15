"""
Quick test: Run the YouTube-to-Blog pipeline with a single video.

Usage:
    1. Copy .env.example to .env and fill in your API keys
    2. Run: python test_pipeline.py VIDEO_URL
"""

import sys
from pipelines.youtube_to_blog import run

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pipeline.py YOUTUBE_URL")
        print("Example: python test_pipeline.py https://www.youtube.com/watch?v=ABC123")
        sys.exit(1)

    run(sys.argv[1])
