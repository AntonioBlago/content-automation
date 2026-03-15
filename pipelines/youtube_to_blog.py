"""
Pipeline: YouTube Video -> Blog Post

1. Pull transcript from YouTube video
2. Send to Claude API with blog template prompt
3. Output formatted blog post (Markdown + HTML)

Usage:
    python -m pipelines.youtube_to_blog VIDEO_URL [--language de]
    python -m pipelines.youtube_to_blog https://www.youtube.com/watch?v=ABC123
"""

import argparse
import io
import json
import os
import sys

# Fix Windows console encoding for emojis/umlauts
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import re
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, OUTPUT_DIR, BLOG_LANGUAGE


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url}")


def get_transcript(video_id: str, language: str = "de") -> str:
    """Fetch transcript from YouTube video."""
    ytt = YouTubeTranscriptApi()
    try:
        entries = ytt.fetch(video_id, languages=[language, "en", "de"])
        return " ".join(entry.text for entry in entries)
    except Exception as e:
        print(f"Error fetching transcript: {e}")
        # Try listing available transcripts
        try:
            transcript_list = ytt.list(video_id)
            # Pick the first available transcript
            first = next(iter(transcript_list))
            entries = first.fetch()
            return " ".join(entry.text for entry in entries)
        except Exception as e2:
            raise RuntimeError(f"No transcript available: {e2}")


def get_video_metadata(video_id: str) -> dict:
    """Get basic video metadata from YouTube oEmbed API (no API key needed)."""
    import requests
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title", ""),
            "author": data.get("author_name", ""),
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
    except Exception:
        return {"title": "", "author": "", "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


def transcript_to_blog(transcript: str, metadata: dict, language: str = "de") -> dict:
    """Send transcript to Claude API and get a structured blog post back."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    lang_instruction = {
        "de": "Schreibe den Blogartikel auf Deutsch. Verwende echte deutsche Umlaute (ae, oe, ue, ss).",
        "en": "Write the blog post in English.",
    }.get(language, f"Write the blog post in {language}.")

    prompt = f"""Du bist ein erfahrener Content-Writer. Erstelle aus dem folgenden YouTube-Transkript einen
hochwertigen Blogartikel.

{lang_instruction}

## Video-Infos
- Titel: {metadata.get('title', 'Unbekannt')}
- Autor: {metadata.get('author', 'Unbekannt')}
- URL: {metadata.get('url', '')}

## Transkript
{transcript}

## Aufgabe
Erstelle einen strukturierten Blogartikel mit:

1. **SEO-optimierter Titel** (H1) - nicht identisch mit dem Video-Titel, aber thematisch passend
2. **Meta Description** (max. 155 Zeichen)
3. **Einleitung** - Hook + Relevanz des Themas (2-3 Saetze)
4. **Hauptteil** - Logisch gegliedert mit H2/H3-Ueberschriften, Key Takeaways hervorheben
5. **Fazit** - Zusammenfassung + Call-to-Action
6. **FAQ-Sektion** - 3-5 relevante Fragen und Antworten (gut fuer SEO)

## Regeln
- Kein Copy-Paste vom Transkript - umformulieren und strukturieren
- Fachbegriffe erklaeren, aber nicht herunterspielen
- Absaetze kurz halten (max 3-4 Saetze)
- Wo sinnvoll: Aufzaehlungen und Listen verwenden
- Interne Verlinkungsvorschlaege als [LINK: Thema] markieren
- Am Ende: Verweis auf das Original-Video einbauen

WICHTIG fuer die JSON-Ausgabe:
- Verwende KEINE doppelten Anfuehrungszeichen innerhalb von JSON-String-Werten
- Verwende stattdessen einfache Anfuehrungszeichen oder typografische Anfuehrungszeichen
- Alle doppelten Anfuehrungszeichen in Texten muessen escaped werden als \\"

Antworte im folgenden JSON-Format:
{{
    "title": "SEO-optimierter Titel",
    "meta_description": "Meta Description max 155 Zeichen",
    "slug": "url-freundlicher-slug",
    "tags": ["tag1", "tag2", "tag3"],
    "content_markdown": "Der komplette Artikel in Markdown",
    "estimated_reading_time": "X min"
}}"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse the JSON response
    response_text = response.content[0].text
    response_text = _extract_json(response_text)
    response_text = _fix_json_control_chars(response_text)

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        # If JSON parsing fails, return raw text
        return {
            "title": metadata.get("title", "Blog Post"),
            "meta_description": "",
            "slug": "blog-post",
            "tags": [],
            "content_markdown": response_text,
            "content_html": "",
            "estimated_reading_time": "5 min",
        }


def _extract_json(text: str) -> str:
    """Extract JSON object from text, handling code blocks and strings with braces."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text.strip())

    start = text.find('{')
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return text[start:]


def _fix_json_control_chars(text: str) -> str:
    """Fix unescaped control characters inside JSON string values."""
    result = []
    in_string = False
    escape = False
    for c in text:
        if escape:
            result.append(c)
            escape = False
            continue
        if c == '\\':
            result.append(c)
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string and c == '\n':
            result.append('\\n')
            continue
        if in_string and c == '\r':
            result.append('\\r')
            continue
        if in_string and c == '\t':
            result.append('\\t')
            continue
        result.append(c)
    return ''.join(result)


def save_blog_post(blog_data: dict, video_id: str) -> dict:
    """Save blog post as Markdown and JSON files."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = blog_data.get("slug", video_id)
    base_name = f"{date_str}_{slug}"

    # Save Markdown
    md_path = os.path.join(OUTPUT_DIR, f"{base_name}.md")
    md_content = f"""---
title: "{blog_data['title']}"
date: {date_str}
description: "{blog_data.get('meta_description', '')}"
tags: {json.dumps(blog_data.get('tags', []))}
reading_time: "{blog_data.get('estimated_reading_time', '')}"
source_video: "https://www.youtube.com/watch?v={video_id}"
---

{blog_data.get('content_markdown', '')}
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Save full JSON (for programmatic use / CMS import)
    json_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(blog_data, f, ensure_ascii=False, indent=2)

    return {"markdown": md_path, "json": json_path}


def run(video_url: str, language: str = None):
    """Run the full YouTube-to-Blog pipeline."""
    lang = language or BLOG_LANGUAGE

    print(f"[1/4] Extracting video ID from: {video_url}")
    video_id = extract_video_id(video_url)
    print(f"       Video ID: {video_id}")

    print(f"[2/4] Fetching metadata...")
    metadata = get_video_metadata(video_id)
    print(f"       Title: {metadata.get('title', 'N/A')}")

    print(f"[3/4] Fetching transcript (language: {lang})...")
    transcript = get_transcript(video_id, lang)
    word_count = len(transcript.split())
    print(f"       Transcript: {word_count} words")

    print(f"[4/4] Generating blog post via Claude API...")
    blog_data = transcript_to_blog(transcript, metadata, lang)

    paths = save_blog_post(blog_data, video_id)
    print(f"\nDone!")
    print(f"  Markdown: {paths['markdown']}")
    print(f"  JSON:     {paths['json']}")
    print(f"  Title:    {blog_data.get('title', 'N/A')}")
    print(f"  Reading:  {blog_data.get('estimated_reading_time', 'N/A')}")

    return blog_data, paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert YouTube video to blog post")
    parser.add_argument("video_url", help="YouTube video URL or ID")
    parser.add_argument("--language", "-l", default=None, help="Blog language (default: from .env)")
    args = parser.parse_args()

    run(args.video_url, args.language)
