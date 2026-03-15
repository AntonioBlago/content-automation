# Content Automation System

Automated content repurposing pipeline: **YouTube/Podcast -> SEO-optimized Blog -> WordPress**.

Built with Claude API, [Visibly AI](https://www.antonioblago.com/register) for keyword research, and WordPress REST API.

## What it does

```
YouTube Video / Podcast Episode
        |
   [1] Transcript Extraction (yt-dlp + youtube-transcript-api)
        |
   [2] Blog Post Generation (Claude API)
        |
   [3] SEO Keyword Research (Visibly AI - search volume, competition)
        |
   [4] Blog Optimization (Claude API - targets best keywords)
        |
   [5] Post-Optimization Analysis (density, placement, score)
        |
   [6] Publish to WordPress (HTML, categories, tags, as draft)
```

## Features

- **YouTube to Blog** - Short videos (3-10 min) to structured blog posts
- **Podcast to Blog** - Long episodes (30-90+ min) with chunked processing
- **SEO Optimization** - Automatic keyword research via Visibly AI, targets best keywords by search volume
- **WordPress Publishing** - Auto-publish as draft with categories, tags, meta description
- **Batch Processing** - Daily cron job processes all new channel videos
- **PythonAnywhere Ready** - Runs as scheduled task, no server needed

## Quick Start

### 1. Install

```bash
git clone https://github.com/AntonioBlago/content-automation.git
cd content-automation
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

| Variable | Required | Source |
|----------|----------|--------|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com) |
| `YOUTUBE_CHANNEL_ID` | Yes | Your channel ID (starts with `UC...`) |
| `VISIBLYAI_API_KEY` | Optional | [antonioblago.com/register](https://www.antonioblago.com/register) (free tier available) |
| `WORDPRESS_URL` | Optional | Your WordPress site URL |
| `WORDPRESS_USER` | Optional | WordPress username |
| `WORDPRESS_APP_PASSWORD` | Optional | WordPress Admin > Users > Application Passwords |

### 3. Run

**Single video:**
```bash
python -m pipelines.youtube_to_blog https://www.youtube.com/watch?v=VIDEO_ID
```

**Podcast episode:**
```bash
python -m pipelines.podcast_to_blog https://www.youtube.com/watch?v=VIDEO_ID
```

**SEO optimize a generated blog post:**
```bash
python -m pipelines.seo_optimize output/2025-01-01_my-post.json
```

**Full daily batch (for cron/PythonAnywhere):**
```bash
python run_daily.py
```

## Pipeline Details

### YouTube to Blog (`pipelines/youtube_to_blog.py`)

1. Extracts video ID from URL
2. Fetches metadata via oEmbed API (no API key needed)
3. Pulls transcript via `youtube-transcript-api` (German/English)
4. Sends to Claude API with SEO blog prompt
5. Outputs Markdown + JSON with frontmatter (title, meta, slug, tags)

### Podcast to Blog (`pipelines/podcast_to_blog.py`)

Same as above but handles long content:
- Uses `yt-dlp` for more reliable subtitle extraction
- Chunks long transcripts (>80k chars) and summarizes each part
- Generates comprehensive long-form articles with key takeaways
- YAML frontmatter format (more reliable than JSON for long content)

### SEO Optimization (`pipelines/seo_optimize.py`)

1. Extracts keyword ideas from blog content via Claude
2. Validates keywords via [Visibly AI API](https://www.antonioblago.com/register) (search volume, competition, CPC)
3. Picks best primary keyword (highest SV + lowest competition)
4. Re-optimizes the blog post targeting that keyword
5. Runs 9-point analysis (keyword density, placement, structure)

### WordPress Publisher (`pipelines/publish_wordpress.py`)

- Converts Markdown to HTML
- Creates/updates posts via WordPress REST API
- Uses `?rest_route=` parameter (works with nginx configs that block `/wp-json/`)
- Auto-creates tags, maps category slugs to IDs
- Publishes as draft by default (use `--publish` for immediate)

### Daily Runner (`run_daily.py`)

- Checks YouTube channel RSS for new videos
- Tracks processed videos (skips duplicates)
- Auto-detects podcasts (>10 min) vs short videos
- Runs SEO optimization if `VISIBLYAI_API_KEY` is set
- Publishes to WordPress if configured
- Logs all activity to `output/daily_log.json`

## Deploy on PythonAnywhere

1. Upload the project to PythonAnywhere
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` with your API keys
4. Add a **Daily Scheduled Task**: `python /home/yourusername/content-automation/run_daily.py`

## Customize

### WordPress Categories

Edit the `CATEGORIES` dict in `pipelines/publish_wordpress.py` and `pipelines/seo_optimize.py` to match your WordPress site:

```python
# Find your category IDs:
# GET https://yoursite.com/?rest_route=/wp/v2/categories
CATEGORIES = {
    "seo": 37,
    "podcast": 226,
    # Add your categories here
}
```

### Blog Language

Set `BLOG_LANGUAGE=en` in `.env` for English output. The prompts adapt automatically.

### Claude Model

Set `CLAUDE_MODEL=claude-opus-4-6` in `.env` for higher quality (slower, more expensive).

## Project Structure

```
content-automation/
├── .env.example            # Template for API keys
├── config.py               # Central configuration
├── requirements.txt        # Python dependencies
├── run_daily.py            # Daily batch runner (cron job)
├── test_pipeline.py        # Quick test script
├── pipelines/
│   ├── youtube_to_blog.py  # Video -> Blog post
│   ├── podcast_to_blog.py  # Podcast -> Long-form blog
│   ├── seo_optimize.py     # Keyword research + optimization
│   └── publish_wordpress.py # -> WordPress (HTML, tags, categories)
├── templates/
│   └── blog_prompt_de.txt  # German blog prompt template
└── output/                 # Generated content (gitignored)
```

## Requirements

- Python 3.9+
- [Anthropic API key](https://console.anthropic.com) (Claude API)
- [Visibly AI API key](https://www.antonioblago.com/register) (optional, for SEO keyword research)
- WordPress site with Application Passwords enabled (optional)

## Credits

Built by [Antonio Blago](https://antonioblago.de) using:
- [Claude API](https://docs.anthropic.com) by Anthropic
- [Visibly AI MCP Server](https://github.com/antonioblago/visiblyai-mcp-server) for SEO keyword research
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for YouTube transcript extraction

## License

MIT
