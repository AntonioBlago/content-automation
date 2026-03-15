"""
Publisher: Push blog post to WordPress via REST API.

Requires WordPress Application Password (not regular password):
  WordPress Admin -> Users -> Profile -> Application Passwords

Usage:
    python -m pipelines.publish_wordpress output/2026-03-15_my-blog-post.json [--draft] [--category podcast]
"""

import argparse
import io
import json
import os
import sys

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import markdown
import requests
from config import OUTPUT_DIR

# User-Agent header (some WordPress installs with nginx block requests without it)
HEADERS = {"User-Agent": "ContentAutomation/1.0"}

# WordPress category slug -> ID mapping (customize for your site)
# Find your IDs: GET /wp-json/wp/v2/categories or ?rest_route=/wp/v2/categories
CATEGORIES = {
    "analyse": 177,
    "automation": 186,
    "case-study": 104,
    "cro": 166,
    "geo": 214,
    "glossar": 96,
    "ki": 205,
    "ki-tools": 206,
    "kundengewinnung": 107,
    "local": 180,
    "offpage-optimierung": 174,
    "onpage-optimierung": 173,
    "podcast": 226,
    "seo": 37,
    "tools": 189,
    "shopify": 199,
    "strategien": 176,
    "technisches-seo": 175,
}


def _wp_request(method, url, wp_user, wp_app_password, **kwargs):
    """Make a WordPress API request using ?rest_route= format with proper headers."""
    kwargs.setdefault("headers", {}).update(HEADERS)
    kwargs["auth"] = (wp_user, wp_app_password)
    kwargs.setdefault("timeout", 30)
    return requests.request(method, url, **kwargs)


def _api_url(wp_url, route):
    """Build WordPress REST API URL using ?rest_route= parameter (bypasses nginx block on /wp-json/)."""
    return f"{wp_url.rstrip('/')}/?rest_route={route}"


def publish_to_wordpress(
    blog_json_path: str,
    wp_url: str,
    wp_user: str,
    wp_app_password: str,
    status: str = "draft",
    category_slugs: list = None,
) -> dict:
    """Publish a blog post JSON to WordPress via REST API."""

    with open(blog_json_path, "r", encoding="utf-8") as f:
        blog_data = json.load(f)

    # Convert markdown to HTML for WordPress
    md_content = blog_data.get("content_markdown", "")
    content = markdown.markdown(md_content, extensions=["tables", "fenced_code", "nl2br"])

    # Build the post payload
    post_data = {
        "title": blog_data["title"],
        "content": content,
        "status": status,
        "excerpt": blog_data.get("meta_description", ""),
        "slug": blog_data.get("slug", ""),
        "format": "standard",
    }

    # Add categories
    if category_slugs:
        cat_ids = []
        for slug in category_slugs:
            cat_id = CATEGORIES.get(slug.lower())
            if cat_id:
                cat_ids.append(cat_id)
            else:
                # Try to find category via API
                found_id = _find_category(wp_url, wp_user, wp_app_password, slug)
                if found_id:
                    cat_ids.append(found_id)
        if cat_ids:
            post_data["categories"] = cat_ids

    # Auto-detect podcast from source JSON
    if not category_slugs and blog_data.get("source_video"):
        # Check if this was a podcast (from frontmatter type field or key_takeaways presence)
        if blog_data.get("key_takeaways") or blog_data.get("type") == "podcast":
            post_data["categories"] = [CATEGORIES["podcast"]]

    # Add tags if available
    if blog_data.get("tags"):
        tag_ids = []
        for tag_name in blog_data["tags"]:
            tag_id = _get_or_create_tag(wp_url, wp_user, wp_app_password, tag_name)
            if tag_id:
                tag_ids.append(tag_id)
        if tag_ids:
            post_data["tags"] = tag_ids

    # Create the post
    url = _api_url(wp_url, "/wp/v2/posts")
    response = _wp_request("POST", url, wp_user, wp_app_password, json=post_data)
    response.raise_for_status()

    result = response.json()
    return {
        "id": result["id"],
        "url": result["link"],
        "status": result["status"],
        "title": result["title"]["rendered"],
    }


def _find_category(wp_url, wp_user, wp_app_password, slug):
    """Find category by slug via API."""
    url = _api_url(wp_url, "/wp/v2/categories")
    resp = _wp_request("GET", url, wp_user, wp_app_password, params={"slug": slug})
    if resp.ok and resp.json():
        return resp.json()[0]["id"]
    return None


def _get_or_create_tag(wp_url, wp_user, wp_app_password, tag_name):
    """Get existing tag ID or create new tag."""
    url = _api_url(wp_url, "/wp/v2/tags")

    # Search for existing tag
    resp = _wp_request("GET", url, wp_user, wp_app_password, params={"search": tag_name})
    if resp.ok and resp.json():
        for tag in resp.json():
            if tag["name"].lower() == tag_name.lower():
                return tag["id"]

    # Create new tag
    resp = _wp_request("POST", url, wp_user, wp_app_password, json={"name": tag_name})
    if resp.ok:
        return resp.json()["id"]

    return None


def run(json_path: str, status: str = "draft", category_slugs: list = None):
    """Publish a blog post to WordPress."""
    from config import WORDPRESS_URL, WORDPRESS_USER, WORDPRESS_APP_PASSWORD

    if not all([WORDPRESS_URL, WORDPRESS_USER, WORDPRESS_APP_PASSWORD]):
        print("Error: Set WORDPRESS_URL, WORDPRESS_USER, and WORDPRESS_APP_PASSWORD in .env")
        sys.exit(1)

    print(f"Publishing to WordPress ({status})...")
    print(f"  Source: {json_path}")

    result = publish_to_wordpress(
        json_path, WORDPRESS_URL, WORDPRESS_USER, WORDPRESS_APP_PASSWORD,
        status, category_slugs,
    )

    print(f"\nPublished!")
    print(f"  ID:     {result['id']}")
    print(f"  Title:  {result['title']}")
    print(f"  URL:    {result['url']}")
    print(f"  Status: {result['status']}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish blog post to WordPress")
    parser.add_argument("json_path", help="Path to blog post JSON file")
    parser.add_argument("--publish", action="store_true", help="Publish immediately (default: draft)")
    parser.add_argument("--category", "-c", action="append", dest="categories",
                        help="Category slug(s), e.g. --category podcast --category seo")
    args = parser.parse_args()

    status = "publish" if args.publish else "draft"
    run(args.json_path, status, args.categories)
