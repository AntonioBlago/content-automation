"""Batch process all podcast episodes from the channel."""
import io
import sys
import json
import os
import time
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from config import OUTPUT_DIR

ALREADY_PROCESSED = set()  # Add video IDs to skip


def main():
    with open(os.path.join(OUTPUT_DIR, "podcast_episodes_filtered.json"), "r", encoding="utf-8") as f:
        episodes = json.load(f)

    total = len(episodes)
    skipped = 0
    success = 0
    failed = 0
    results = []

    print(f"{'='*60}")
    print(f"PODCAST BATCH PROCESSING - {total} episodes")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    for i, ep in enumerate(episodes):
        vid = ep["id"]
        title = ep["title"]
        dur = ep["duration"] // 60

        if vid in ALREADY_PROCESSED:
            print(f"[{i+1}/{total}] SKIP (already done): {title}")
            skipped += 1
            continue

        print(f"\n{'='*60}")
        print(f"[{i+1}/{total}] {title} ({dur} min)")
        print(f"{'='*60}")

        try:
            # Step 1: Generate blog
            if dur > 15:
                from pipelines.podcast_to_blog import run as podcast_run
                blog_data, paths = podcast_run(ep["url"])
            else:
                from pipelines.youtube_to_blog import run as video_run
                blog_data, paths = video_run(ep["url"])

            # Step 2: SEO optimize (if Visibly AI key is set)
            seo_score = None
            optimized_path = paths["json"]
            if os.getenv("VISIBLYAI_API_KEY"):
                try:
                    from pipelines.seo_optimize import run as seo_run
                    optimized_data, analysis = seo_run(paths["json"])
                    seo_score = analysis.get("score_pct", 0)
                    opt_path = paths["json"].replace(".json", "_optimized.json")
                    if os.path.exists(opt_path):
                        optimized_path = opt_path
                except Exception as e:
                    print(f"  SEO optimization failed (non-fatal): {e}")

            # Step 3: Publish to WordPress
            wp_url = None
            if os.getenv("WORDPRESS_URL"):
                try:
                    from pipelines.publish_wordpress import run as wp_run
                    is_podcast = dur > 15
                    cats = ["podcast", "seo"] if is_podcast else ["seo"]
                    wp_result = wp_run(optimized_path, status="draft", category_slugs=cats)
                    wp_url = wp_result.get("url", "")
                except Exception as e:
                    print(f"  WordPress publish failed (non-fatal): {e}")

            ALREADY_PROCESSED.add(vid)
            success += 1
            results.append({
                "video_id": vid,
                "title": blog_data.get("title", title),
                "status": "success",
                "seo_score": seo_score,
                "wp_url": wp_url,
                "blog_path": paths["markdown"],
            })
            print(f"\n  -> SUCCESS | SEO: {seo_score}% | WP: {wp_url or 'skipped'}")

        except Exception as e:
            failed += 1
            results.append({
                "video_id": vid,
                "title": title,
                "status": "failed",
                "error": str(e),
            })
            print(f"\n  -> FAILED: {e}")

        # Small delay between API calls
        time.sleep(2)

    # Summary
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"Total: {total} | Success: {success} | Failed: {failed} | Skipped: {skipped}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Save results
    results_path = os.path.join(OUTPUT_DIR, "batch_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Results saved: {results_path}")

    # Print summary table
    print(f"\nResults:")
    for r in results:
        status = r["status"].upper()
        score = f"{r.get('seo_score', '-')}%" if r.get("seo_score") else "-"
        print(f"  [{status}] {r['title'][:60]} | SEO: {score}")


if __name__ == "__main__":
    main()
