"""
Pipeline: SEO Keyword Research + Blog Optimization

1. Extract topic keywords from blog draft
2. Validate keywords via Visibly AI API (search volume, competition)
3. Optimize blog post with Claude API targeting best keywords
4. Analyze optimization results

Usage:
    python -m pipelines.seo_optimize input.json [--publish WP_POST_ID]
"""

import argparse
import io
import json
import math
import os
import re
import sys
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
import httpx
import markdown
import requests

from config import ANTHROPIC_API_KEY, VISIBLYAI_API_KEY, VISIBLYAI_BASE_URL, CLAUDE_MODEL, OUTPUT_DIR


# ── Visibly AI API Client ─────────────────────────────────────────────────


def _visiblyai_post(endpoint: str, payload: dict) -> dict:
    """Call Visibly AI API."""
    api_key = VISIBLYAI_API_KEY
    if not api_key:
        raise RuntimeError("VISIBLYAI_API_KEY not set in .env")

    with httpx.Client(base_url=VISIBLYAI_BASE_URL, timeout=60.0) as client:
        resp = client.post(
            endpoint,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Visibly AI API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


def validate_keywords(keywords: list, location: str = "Germany", language: str = "German") -> list:
    """Validate keywords: get search volume, competition, CPC."""
    result = _visiblyai_post("/tools/validate-keywords", {
        "keywords": keywords,
        "location": location,
        "language": language,
        "top_n": 50,
    })
    data = result.get("data", [])
    # Filter out keywords with no search volume and sort by opportunity
    valid = []
    for kw in data:
        sv = kw.get("search_volume")
        if sv and not (isinstance(sv, float) and math.isnan(sv)):
            valid.append(kw)
    valid.sort(key=lambda x: x.get("search_volume", 0), reverse=True)
    return valid


def classify_keywords(keywords: list, brand_name: str = "") -> list:
    """Classify keywords by intent."""
    result = _visiblyai_post("/tools/classify-keywords", {
        "keywords": keywords,
        "language": "German",
        "location": "Germany",
    })
    return result.get("data", [])


# ── Keyword Extraction ─────────────────────────────────────────────────

def extract_topic_keywords(blog_data: dict) -> list:
    """Use Claude to extract keyword ideas from the blog content."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    title = blog_data.get("title", "")
    content = blog_data.get("content_markdown", "")[:3000]  # First 3k chars
    tags = blog_data.get("tags", [])

    prompt = f"""Extrahiere 10-15 relevante SEO-Keyword-Ideen aus diesem Blogartikel.
Fokussiere dich auf Keywords, die ein deutscher Nutzer bei Google suchen wuerde.

Titel: {title}
Tags: {', '.join(tags) if tags else 'keine'}
Inhalt (Auszug): {content}

Regeln:
- Mischung aus Short-Tail (2 Woerter) und Long-Tail (3-5 Woerter)
- Keine Brand-Keywords
- Deutsch, Kleinschreibung
- Ein Keyword pro Zeile, keine Nummerierung

Antwort nur mit den Keywords, eine pro Zeile:"""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    keywords = [line.strip().strip("-").strip("*").strip() for line in resp.content[0].text.strip().split("\n")]
    return [kw for kw in keywords if kw and len(kw) > 2]


# ── Optimization ───────────────────────────────────────────────────────

def optimize_blog(blog_data: dict, keyword_data: list) -> dict:
    """Optimize blog post targeting the best keywords."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Pick primary keyword (highest SV with low competition)
    primary = keyword_data[0]
    secondary = keyword_data[1:6]

    primary_kw = primary["keyword"]
    primary_sv = int(primary.get("search_volume", 0))

    sec_lines = "\n".join(
        f'- "{kw["keyword"]}" ({int(kw.get("search_volume", 0))} SV)'
        for kw in secondary
    )

    prompt = f"""Optimiere diesen Blogartikel fuer das Hauptkeyword "{primary_kw}" ({primary_sv} SV).

Sekundaere Keywords:
{sec_lines}

SEO-Optimierungsregeln:
1. H1: Hauptkeyword "{primary_kw}" vorne, max 60 Zeichen
2. Meta Description: max 155 Zeichen, Hauptkeyword + CTA
3. Erster Absatz: Hauptkeyword in den ersten 100 Woertern
4. Keyword-Dichte: Hauptkeyword 4-8x, Sekundaerkeywords je 2-3x
5. Sekundaere Keywords in H2/H3-Ueberschriften einbauen
6. FAQ mit Long-Tail Varianten der Keywords
7. Slug: URL-freundlich aus Hauptkeyword ableiten

Starte direkt mit --- (KEIN Code-Block):
---
title: "Titel in Anfuehrungszeichen"
meta_description: "Meta in Anfuehrungszeichen"
slug: url-slug
tags: [Tag1, Tag2, Tag3, Tag4, Tag5]
estimated_reading_time: "X min"
primary_keyword: "{primary_kw}"
---

Optimierter Artikel in Markdown...

Aktueller Artikel:
{blog_data['content_markdown']}"""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    text = resp.content[0].text.strip()

    # Remove code block wrappers
    text = re.sub(r'^```(?:yaml|markdown)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    text = re.sub(r'\n```\s*\n', '\n', text)

    # Parse frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.DOTALL)
    if fm_match:
        fm = {}
        for line in fm_match.group(1).split('\n'):
            m = re.match(r'^(\w[\w_]+):\s+(.+)$', line)
            if m:
                k = m.group(1)
                v = m.group(2).strip().strip('"').strip("'")
                if v.startswith('[') and v.endswith(']'):
                    v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(',')]
                fm[k] = v

        # Enforce title max length
        title = fm.get("title", blog_data.get("title", ""))
        if len(title) > 60:
            title = title[:57] + "..."

        return {
            "title": title,
            "meta_description": fm.get("meta_description", ""),
            "slug": fm.get("slug", ""),
            "tags": fm.get("tags", []),
            "content_markdown": fm_match.group(2).strip(),
            "estimated_reading_time": fm.get("estimated_reading_time", ""),
            "primary_keyword": primary_kw,
            "type": blog_data.get("type", ""),
            "key_takeaways": blog_data.get("key_takeaways", []),
        }

    # Fallback
    return {**blog_data, "content_markdown": text, "primary_keyword": primary_kw}


# ── Analysis ───────────────────────────────────────────────────────────

def analyze_optimization(blog_data: dict, keyword_data: list) -> dict:
    """Analyze keyword optimization of the blog post."""
    title = blog_data.get("title", "")
    content = blog_data.get("content_markdown", "")
    meta = blog_data.get("meta_description", "")
    slug = blog_data.get("slug", "")
    full_text = (title + " " + content).lower()
    word_count = len(content.split())

    primary_kw = blog_data.get("primary_keyword", keyword_data[0]["keyword"] if keyword_data else "")
    secondary_kws = [kw["keyword"] for kw in keyword_data[1:6]]

    # Keyword density
    primary_count = full_text.count(primary_kw.lower())
    density = (primary_count / word_count * 100) if word_count > 0 else 0

    # Placement checks
    first_p_match = re.search(r'^(.*?\n\n)', content)
    first_paragraph = first_p_match.group(1).lower() if first_p_match else content[:500].lower()

    checks = {
        "kw_in_title": primary_kw.lower() in title.lower(),
        "kw_in_meta": primary_kw.lower() in meta.lower(),
        "kw_in_first_paragraph": primary_kw.lower() in first_paragraph,
        "kw_in_slug": primary_kw.lower().replace(" ", "-") in slug or primary_kw.split()[0].lower() in slug,
        "title_length_ok": len(title) <= 60,
        "meta_length_ok": 0 < len(meta) <= 155,
        "has_faq": "faq" in full_text or "häufige fragen" in full_text,
        "word_count_ok": word_count > 1000,
        "density_ok": 0.5 <= density <= 2.5,
    }

    # H2 keyword coverage
    h2s = re.findall(r'^## (.+)$', content, re.MULTILINE)
    h2_with_kw = sum(1 for h in h2s if any(kw.lower() in h.lower() for kw in [primary_kw] + secondary_kws))

    score = sum(1 for v in checks.values() if v)
    total = len(checks)

    return {
        "primary_keyword": primary_kw,
        "primary_count": primary_count,
        "density_pct": round(density, 2),
        "word_count": word_count,
        "title_length": len(title),
        "meta_length": len(meta),
        "h2_count": len(h2s),
        "h2_with_keywords": h2_with_kw,
        "checks": checks,
        "score": score,
        "total": total,
        "score_pct": round(score / total * 100),
        "secondary_counts": {
            kw: full_text.count(kw.lower()) for kw in secondary_kws
        },
    }


# ── WordPress Publishing ──────────────────────────────────────────────

def publish_to_wordpress(blog_data: dict, post_id: int = None, category_ids: list = None) -> dict:
    """Publish or update a WordPress post."""
    from config import WORDPRESS_URL, WORDPRESS_USER, WORDPRESS_APP_PASSWORD
    from pipelines.publish_wordpress import _get_or_create_tag

    html = markdown.markdown(blog_data["content_markdown"], extensions=["tables", "fenced_code"])

    payload = {
        "title": blog_data["title"],
        "content": html,
        "slug": blog_data.get("slug", ""),
        "excerpt": blog_data.get("meta_description", ""),
        "status": "draft",
    }

    if category_ids:
        payload["categories"] = category_ids

    if blog_data.get("tags"):
        tag_ids = []
        for t in blog_data["tags"]:
            tid = _get_or_create_tag(WORDPRESS_URL, WORDPRESS_USER, WORDPRESS_APP_PASSWORD, t)
            if tid:
                tag_ids.append(tid)
        payload["tags"] = tag_ids

    headers = {"User-Agent": "ContentAutomation/1.0"}

    if post_id:
        route = f"/wp/v2/posts/{post_id}"
    else:
        route = "/wp/v2/posts"

    r = requests.post(
        f"{WORDPRESS_URL}/?rest_route={route}",
        json=payload,
        auth=(WORDPRESS_USER, WORDPRESS_APP_PASSWORD),
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    return {"id": result["id"], "url": result["link"], "status": result["status"]}


# ── Main Pipeline ─────────────────────────────────────────────────────

# WordPress category slug -> ID mapping (customize for your site)
# Find your category IDs: wp-json/wp/v2/categories or ?rest_route=/wp/v2/categories
CATEGORIES = {
    "seo": 37, "podcast": 226, "analyse": 177, "automation": 186,
    "ki": 205, "tools": 189, "strategien": 176, "glossar": 96,
}


def run(input_json: str, wp_post_id: int = None, category_slugs: list = None):
    """Run the full SEO optimization pipeline."""

    print(f"[1/5] Loading blog post: {input_json}")
    with open(input_json, "r", encoding="utf-8") as f:
        blog_data = json.load(f)
    print(f"       Title: {blog_data.get('title', 'N/A')}")

    print(f"[2/5] Extracting keyword ideas via Claude...")
    keyword_ideas = extract_topic_keywords(blog_data)
    print(f"       Found {len(keyword_ideas)} keyword ideas")
    for kw in keyword_ideas[:5]:
        print(f"         - {kw}")

    print(f"[3/5] Validating keywords via Visibly AI (SV, competition)...")
    keyword_data = validate_keywords(keyword_ideas)

    if not keyword_data:
        # Retry with broader keyword variations
        print("       No results, retrying with English/broader terms...")
        broader = [kw.replace("ue", "u").replace("ae", "a").replace("oe", "o") for kw in keyword_ideas[:5]]
        # Also add the title words as keywords
        title_words = blog_data.get("title", "").lower().split()
        bigrams = [f"{title_words[i]} {title_words[i+1]}" for i in range(len(title_words)-1)]
        keyword_data = validate_keywords(keyword_ideas + broader + bigrams)

    if not keyword_data:
        print("       No keywords with search volume found. Skipping optimization.")
        return blog_data, {"score": 0, "total": 9, "score_pct": 0}

    print(f"       {len(keyword_data)} keywords with search volume")
    print(f"       Best keyword: \"{keyword_data[0]['keyword']}\" ({int(keyword_data[0]['search_volume'])} SV)")
    for kw in keyword_data[:5]:
        sv = int(kw.get("search_volume", 0))
        comp = kw.get("competition", "?")
        print(f"         - \"{kw['keyword']}\" ({sv} SV, {comp})")

    print(f"[4/5] Optimizing blog post for \"{keyword_data[0]['keyword']}\"...")
    optimized = optimize_blog(blog_data, keyword_data)

    # Save optimized version
    base = os.path.splitext(os.path.basename(input_json))[0]
    output_path = os.path.join(OUTPUT_DIR, f"{base}_optimized.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(optimized, f, ensure_ascii=False, indent=2)
    print(f"       Saved: {output_path}")

    print(f"[5/5] Analyzing optimization results...")
    analysis = analyze_optimization(optimized, keyword_data)

    # Print analysis
    print(f"\n{'='*50}")
    print(f"SEO OPTIMIZATION REPORT")
    print(f"{'='*50}")
    print(f"Title: {optimized['title']}")
    print(f"Title length: {analysis['title_length']} chars {'[OK]' if analysis['checks']['title_length_ok'] else '[TOO LONG]'}")
    print(f"Meta: {optimized.get('meta_description', '')}")
    print(f"Meta length: {analysis['meta_length']} chars {'[OK]' if analysis['checks']['meta_length_ok'] else '[FIX]'}")
    print(f"Word count: {analysis['word_count']}")
    print(f"\nKEYWORD DENSITY:")
    print(f"  Primary: \"{analysis['primary_keyword']}\" = {analysis['primary_count']}x ({analysis['density_pct']}%) {'[OK]' if analysis['checks']['density_ok'] else '[FIX]'}")
    for kw, count in analysis['secondary_counts'].items():
        print(f"  Secondary: \"{kw}\" = {count}x")
    print(f"\nCHECKLIST:")
    for check, passed in analysis['checks'].items():
        label = check.replace('_', ' ').title()
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"\nSCORE: {analysis['score']}/{analysis['total']} ({analysis['score_pct']}%)")

    # Publish to WordPress if requested
    if wp_post_id is not None:
        cat_ids = [CATEGORIES.get(s, 37) for s in (category_slugs or ["seo"])]
        print(f"\nPublishing to WordPress (post {wp_post_id})...")
        wp_result = publish_to_wordpress(optimized, wp_post_id, cat_ids)
        print(f"  URL: {wp_result['url']}")
        print(f"  Status: {wp_result['status']}")

    return optimized, analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SEO-optimize a blog post")
    parser.add_argument("input_json", help="Path to blog post JSON")
    parser.add_argument("--publish", "-p", type=int, default=None, help="WordPress post ID to update")
    parser.add_argument("--category", "-c", action="append", dest="categories", help="Category slug(s)")
    args = parser.parse_args()

    run(args.input_json, args.publish, args.categories)
