"""
Pipeline: Podcast Episode (YouTube) -> Long-form Blog Post

Handles long podcast episodes (30-90+ min) by:
1. Pulling transcript via yt-dlp (better than youtube-transcript-api for long content)
2. Chunking transcript if needed (Claude context limit)
3. Generating a comprehensive, structured blog article

Usage:
    python -m pipelines.podcast_to_blog VIDEO_URL [--language de]
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# Fix Windows console encoding for emojis/umlauts
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
import requests
import yaml

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, OUTPUT_DIR, BLOG_LANGUAGE


def extract_video_id(url: str) -> str:
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url}")


def get_transcript_ytdlp(video_id: str, language: str = "de") -> str:
    """Fetch transcript using yt-dlp (more reliable for long videos)."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--write-auto-sub",
        "--sub-lang", f"{language},en",
        "--sub-format", "json3",
        "--skip-download",
        "--output", os.path.join(OUTPUT_DIR, f"sub_{video_id}"),
        url,
    ]

    subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    sub_patterns = [
        os.path.join(OUTPUT_DIR, f"sub_{video_id}.{language}.json3"),
        os.path.join(OUTPUT_DIR, f"sub_{video_id}.en.json3"),
    ]

    for sub_path in sub_patterns:
        if os.path.exists(sub_path):
            with open(sub_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            texts = []
            for event in data.get("events", []):
                for seg in event.get("segs", []):
                    text = seg.get("utf8", "").strip()
                    if text and text != "\n":
                        texts.append(text)
            os.remove(sub_path)
            return " ".join(texts)

    # Fallback: try youtube-transcript-api
    print("yt-dlp subtitles not found, trying youtube-transcript-api...")
    from youtube_transcript_api import YouTubeTranscriptApi
    ytt = YouTubeTranscriptApi()
    try:
        entries = ytt.fetch(video_id, languages=[language, "en", "de"])
        return " ".join(entry.text for entry in entries)
    except Exception:
        transcript_list = ytt.list(video_id)
        first = next(iter(transcript_list))
        entries = first.fetch()
        return " ".join(entry.text for entry in entries)


def get_video_metadata(video_id: str) -> dict:
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


def get_video_metadata_ytdlp(video_id: str) -> dict:
    """Get richer metadata via yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [sys.executable, "-m", "yt_dlp", "--dump-json", "--skip-download", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {
                "title": data.get("title", ""),
                "author": data.get("uploader", ""),
                "description": data.get("description", ""),
                "duration": data.get("duration", 0),
                "tags": data.get("tags", []),
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
    except Exception:
        pass
    return get_video_metadata(video_id)


def chunk_transcript(transcript: str, max_chars: int = 80000) -> list:
    if len(transcript) <= max_chars:
        return [transcript]

    words = transcript.split()
    chunks = []
    current = []
    current_len = 0

    for word in words:
        current.append(word)
        current_len += len(word) + 1
        if current_len >= max_chars:
            chunks.append(" ".join(current))
            current = []
            current_len = 0

    if current:
        chunks.append(" ".join(current))

    return chunks


def podcast_to_blog(transcript: str, metadata: dict, language: str = "de") -> dict:
    """Transform podcast transcript into a blog post via Claude API."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    duration_min = metadata.get("duration", 0) // 60
    guest_info = ""
    if metadata.get("description"):
        guest_info = f"\n## Beschreibung\n{metadata['description'][:1000]}"

    lang_instruction = {
        "de": "Schreibe den Blogartikel auf Deutsch. Verwende echte deutsche Umlaute.",
        "en": "Write the blog post in English.",
    }.get(language, f"Write the blog post in {language}.")

    chunks = chunk_transcript(transcript)

    if len(chunks) == 1:
        return _generate_blog(client, chunks[0], metadata, lang_instruction, guest_info, duration_min)
    else:
        print(f"  Long transcript ({len(chunks)} chunks), processing in parts...")
        summaries = []
        for i, chunk in enumerate(chunks):
            print(f"  Summarizing chunk {i+1}/{len(chunks)}...")
            summary = _summarize_chunk(client, chunk, i + 1, len(chunks), metadata)
            summaries.append(summary)

        combined = "\n\n---\n\n".join(summaries)
        return _generate_blog(client, combined, metadata, lang_instruction, guest_info, duration_min, is_summary=True)


def _summarize_chunk(client, chunk: str, part: int, total: int, metadata: dict) -> str:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""Fasse den folgenden Abschnitt ({part}/{total}) eines Podcast-Transkripts zusammen.
Behalte alle wichtigen Aussagen, Zitate, Tipps und Erkenntnisse bei.
Strukturiere die Zusammenfassung thematisch.

Podcast: {metadata.get('title', '')}

Transkript-Abschnitt:
{chunk}

Liefere eine detaillierte Zusammenfassung (ca. 1000-1500 Woerter):"""}],
    )
    return response.content[0].text


def _generate_blog(client, content: str, metadata: dict, lang_instruction: str,
                    guest_info: str, duration_min: int, is_summary: bool = False) -> dict:
    """Generate the final blog post."""
    content_label = "Zusammenfassung des Transkripts" if is_summary else "Transkript"

    prompt = f"""Du bist ein erfahrener Content-Writer.
Erstelle aus dem folgenden Podcast-{content_label} einen ausfuehrlichen, hochwertigen Blogartikel.

{lang_instruction}

## Podcast-Infos
- Titel: {metadata.get('title', 'Unbekannt')}
- Host/Autor: {metadata.get('author', 'Antonio Blago')}
- Dauer: ca. {duration_min} Minuten
- URL: {metadata.get('url', '')}
{guest_info}

## {content_label}
{content}

## Aufgabe
Erstelle einen umfassenden Blogartikel mit:

1. **SEO-optimierter Titel** (H1) - eigenstaendig, nicht identisch mit Podcast-Titel
2. **Meta Description** (max. 155 Zeichen)
3. **Einleitung** - Worum geht es, warum ist das Thema relevant? (3-4 Saetze)
4. **Hauptteil** mit klarer H2/H3-Struktur:
   - Jeden wichtigen Diskussionspunkt als eigenen Abschnitt
   - Zitate der Sprecher einbauen (als Blockquote)
   - Konkrete Tipps und Takeaways hervorheben
5. **Key Takeaways** - Zusammenfassung der wichtigsten Punkte als Liste
6. **Fazit** mit Call-to-Action
7. **FAQ-Sektion** - 5 relevante Fragen und Antworten

## Regeln
- Nicht einfach das Transkript abschreiben - umformulieren und strukturieren
- Praxisnahe, umsetzbare Erkenntnisse betonen
- Fachbegriffe erklaeren
- Absaetze kurz halten (max 3-4 Saetze)
- Listen und Aufzaehlungen verwenden
- Am Ende: Verweis auf die Original-Podcastfolge mit Link
- Zielgruppe: Marketing-Manager, E-Commerce-Verantwortliche, Unternehmer

## Ausgabeformat
Beginne deine Antwort mit einem YAML-Frontmatter-Block (zwischen --- Markern),
dann der komplette Artikel als Markdown.

Beispiel:

---
title: "Dein SEO-optimierter Titel hier"
meta_description: "Deine Meta Description hier (max 155 Zeichen)"
slug: dein-url-slug-hier
tags: [Tag1, Tag2, Tag3, Tag4, Tag5]
estimated_reading_time: "12 min"
key_takeaways:
  - Erster wichtiger Punkt
  - Zweiter wichtiger Punkt
  - Dritter wichtiger Punkt
---

# Dein Titel

Dein Artikel in Markdown..."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text
    return _parse_frontmatter_response(response_text, metadata, duration_min)


def _parse_frontmatter_response(text: str, metadata: dict, duration_min: int) -> dict:
    """Parse YAML frontmatter + markdown response from Claude."""
    text = text.strip()

    # Find frontmatter between --- markers
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.DOTALL)
    if fm_match:
        frontmatter_str = fm_match.group(1)
        content = fm_match.group(2).strip()
        try:
            fm = yaml.safe_load(frontmatter_str)
            return {
                "title": fm.get("title", metadata.get("title", "")),
                "meta_description": fm.get("meta_description", ""),
                "slug": fm.get("slug", "podcast-blog-post"),
                "tags": fm.get("tags", []),
                "content_markdown": content,
                "estimated_reading_time": fm.get("estimated_reading_time", f"{max(duration_min // 4, 5)} min"),
                "key_takeaways": fm.get("key_takeaways", []),
                "type": "podcast",
            }
        except yaml.YAMLError:
            pass

    # Fallback: no frontmatter found, treat entire response as markdown
    return {
        "title": metadata.get("title", "Podcast Blog Post"),
        "meta_description": "",
        "slug": "podcast-blog-post",
        "tags": [],
        "content_markdown": text,
        "estimated_reading_time": f"{max(duration_min // 4, 5)} min",
        "key_takeaways": [],
        "type": "podcast",
    }


def save_blog_post(blog_data: dict, video_id: str) -> dict:
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = blog_data.get("slug", video_id)
    base_name = f"{date_str}_{slug}"

    md_path = os.path.join(OUTPUT_DIR, f"{base_name}.md")
    md_content = f"""---
title: "{blog_data['title']}"
date: {date_str}
description: "{blog_data.get('meta_description', '')}"
tags: {json.dumps(blog_data.get('tags', []), ensure_ascii=False)}
reading_time: "{blog_data.get('estimated_reading_time', '')}"
source_video: "https://www.youtube.com/watch?v={video_id}"
type: podcast
---

{blog_data.get('content_markdown', '')}
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    json_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(blog_data, f, ensure_ascii=False, indent=2)

    return {"markdown": md_path, "json": json_path}


def run(video_url: str, language: str = None):
    lang = language or BLOG_LANGUAGE

    print(f"[1/4] Extracting video ID from: {video_url}")
    video_id = extract_video_id(video_url)

    print(f"[2/4] Fetching metadata...")
    metadata = get_video_metadata_ytdlp(video_id)
    duration_min = metadata.get("duration", 0) // 60
    print(f"       Title: {metadata.get('title', 'N/A')}")
    print(f"       Duration: {duration_min} min")

    print(f"[3/4] Fetching transcript (language: {lang})...")
    transcript = get_transcript_ytdlp(video_id, lang)
    word_count = len(transcript.split())
    print(f"       Transcript: {word_count} words")

    print(f"[4/4] Generating blog post via Claude API...")
    blog_data = podcast_to_blog(transcript, metadata, lang)

    paths = save_blog_post(blog_data, video_id)
    print(f"\nDone!")
    print(f"  Markdown: {paths['markdown']}")
    print(f"  JSON:     {paths['json']}")
    print(f"  Title:    {blog_data.get('title', 'N/A')}")
    print(f"  Reading:  {blog_data.get('estimated_reading_time', 'N/A')}")

    if blog_data.get("key_takeaways"):
        print(f"\n  Key Takeaways:")
        for t in blog_data["key_takeaways"]:
            print(f"    - {t}")

    return blog_data, paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert podcast episode to blog post")
    parser.add_argument("video_url", help="YouTube video URL or ID")
    parser.add_argument("--language", "-l", default=None, help="Blog language")
    args = parser.parse_args()

    run(args.video_url, args.language)
