"""
Daily content automation runner - scheduled on PythonAnywhere.

This script:
1. Checks YouTube channel for new videos/podcasts
2. Generates blog posts from new content
3. Publishes as drafts to WordPress
4. Logs everything

Schedule on PythonAnywhere:
    Tasks -> Daily -> python /home/yourusername/content-automation/run_daily.py
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from config import YOUTUBE_CHANNEL_ID, OUTPUT_DIR, WORDPRESS_URL

LOG_FILE = os.path.join(OUTPUT_DIR, "daily_log.json")
PROCESSED_FILE = os.path.join(OUTPUT_DIR, "processed_videos.json")

# Podcast threshold: videos longer than this (seconds) are treated as podcasts
PODCAST_THRESHOLD = 600  # 10 minutes


def load_processed() -> set:
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed(processed: set):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed), f)


def log_entry(entry: dict):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            log = json.load(f)
    log.append(entry)
    # Keep last 100 entries
    log = log[-100:]
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def get_new_videos(channel_id: str, max_results: int = 10) -> list:
    """Fetch recent videos via yt-dlp."""
    import subprocess
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--playlist-items", f"1-{max_results}",
        "--flat-playlist",
        f"https://www.youtube.com/channel/{channel_id}/videos",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    videos = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            try:
                data = json.loads(line)
                videos.append({
                    "video_id": data["id"],
                    "title": data.get("title", ""),
                    "duration": data.get("duration", 0) or 0,
                    "url": data.get("url", f"https://www.youtube.com/watch?v={data['id']}"),
                })
            except (json.JSONDecodeError, KeyError):
                continue
    return videos


def main():
    print(f"=== Content Automation Daily Run: {datetime.now().isoformat()} ===\n")

    if not YOUTUBE_CHANNEL_ID:
        print("Error: YOUTUBE_CHANNEL_ID not set")
        sys.exit(1)

    processed = load_processed()
    print(f"Already processed: {len(processed)} videos")

    # Get latest videos
    videos = get_new_videos(YOUTUBE_CHANNEL_ID)
    new_videos = [v for v in videos if v["video_id"] not in processed]

    if not new_videos:
        print("No new videos found. Exiting.")
        log_entry({"date": datetime.now().isoformat(), "action": "check", "new_videos": 0})
        return

    print(f"Found {len(new_videos)} new videos to process:\n")

    for video in new_videos[:3]:  # Max 3 per run to stay within API limits
        is_podcast = video["duration"] > PODCAST_THRESHOLD
        content_type = "podcast" if is_podcast else "video"
        print(f"  [{content_type.upper()}] {video['title']} ({video['duration'] // 60} min)")

        try:
            if is_podcast:
                from pipelines.podcast_to_blog import run as podcast_run
                blog_data, paths = podcast_run(video["url"])
            else:
                from pipelines.youtube_to_blog import run as video_run
                blog_data, paths = video_run(video["url"])

            # SEO optimize with Visibly AI keyword research (if API key set)
            seo_result = None
            if os.getenv("VISIBLYAI_API_KEY"):
                try:
                    from pipelines.seo_optimize import run as seo_run
                    categories = ["podcast", "seo"] if is_podcast else ["seo"]
                    optimized_data, seo_result = seo_run(paths["json"], category_slugs=categories)
                    # Update paths to point to optimized version
                    optimized_path = paths["json"].replace(".json", "_optimized.json")
                    if os.path.exists(optimized_path):
                        paths["json"] = optimized_path
                    print(f"  -> SEO Score: {seo_result['score']}/{seo_result['total']} ({seo_result['score_pct']}%)")
                except Exception as e:
                    print(f"  -> SEO optimization failed (non-fatal): {e}")

            # Publish to WordPress as draft (if configured)
            wp_result = None
            if WORDPRESS_URL:
                from pipelines.publish_wordpress import run as wp_publish
                cat_slugs = ["podcast", "seo"] if is_podcast else ["seo"]
                wp_result = wp_publish(paths["json"], status="draft", category_slugs=cat_slugs)

            processed.add(video["video_id"])
            save_processed(processed)

            log_entry({
                "date": datetime.now().isoformat(),
                "action": "published",
                "video_id": video["video_id"],
                "title": blog_data.get("title", ""),
                "type": content_type,
                "blog_path": paths["markdown"],
                "wp_url": wp_result["url"] if wp_result else None,
            })

            print(f"  -> Blog saved: {paths['markdown']}")
            if wp_result:
                print(f"  -> WordPress draft: {wp_result['url']}")
            print()

        except Exception as e:
            print(f"  -> FAILED: {e}\n")
            log_entry({
                "date": datetime.now().isoformat(),
                "action": "error",
                "video_id": video["video_id"],
                "error": str(e),
            })
            continue

    print("Daily run complete.")


if __name__ == "__main__":
    main()
