"""
Batch process: Fetch latest videos from a YouTube channel and generate blog posts.

This is the script you schedule on PythonAnywhere (daily task).

Usage:
    python -m pipelines.batch_youtube [--max 3] [--language de]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from config import OUTPUT_DIR
from pipelines.youtube_to_blog import run as youtube_to_blog


def get_channel_videos_rss(channel_id: str, max_results: int = 5) -> list:
    """Fetch latest videos from YouTube channel via RSS (no API key needed)."""
    import xml.etree.ElementTree as ET

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = requests.get(rss_url, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    videos = []
    for entry in root.findall("atom:entry", ns)[:max_results]:
        video_id = entry.find("yt:videoId", ns).text
        title = entry.find("atom:title", ns).text
        published = entry.find("atom:published", ns).text
        videos.append({
            "video_id": video_id,
            "title": title,
            "published": published,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })

    return videos


def load_processed_log() -> set:
    """Load set of already-processed video IDs."""
    log_path = os.path.join(OUTPUT_DIR, "processed_videos.json")
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_log(processed: set):
    """Save updated processed video IDs."""
    log_path = os.path.join(OUTPUT_DIR, "processed_videos.json")
    with open(log_path, "w") as f:
        json.dump(list(processed), f)


def run_batch(channel_id: str, max_videos: int = 3, language: str = "de"):
    """Process new videos from channel."""
    print(f"Fetching latest videos from channel: {channel_id}")
    videos = get_channel_videos_rss(channel_id, max_results=max_videos * 2)
    print(f"Found {len(videos)} videos in RSS feed")

    processed = load_processed_log()
    new_videos = [v for v in videos if v["video_id"] not in processed]

    if not new_videos:
        print("No new videos to process.")
        return

    print(f"Processing {min(len(new_videos), max_videos)} new videos...\n")

    for video in new_videos[:max_videos]:
        print(f"{'='*60}")
        print(f"Processing: {video['title']}")
        print(f"{'='*60}")
        try:
            blog_data, paths = youtube_to_blog(video["url"], language)
            processed.add(video["video_id"])
            save_processed_log(processed)
            print(f"Blog post saved.\n")
        except Exception as e:
            print(f"FAILED: {e}\n")
            continue

    print(f"Batch complete. {len(processed)} total videos processed.")


if __name__ == "__main__":
    from config import YOUTUBE_CHANNEL_ID

    parser = argparse.ArgumentParser(description="Batch process YouTube channel videos")
    parser.add_argument("--channel", "-c", default=YOUTUBE_CHANNEL_ID, help="YouTube channel ID")
    parser.add_argument("--max", "-m", type=int, default=3, help="Max videos to process")
    parser.add_argument("--language", "-l", default="de", help="Blog language")
    args = parser.parse_args()

    if not args.channel:
        print("Error: Set YOUTUBE_CHANNEL_ID in .env or pass --channel")
        sys.exit(1)

    run_batch(args.channel, args.max, args.language)
