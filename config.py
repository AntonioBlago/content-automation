"""Configuration for content automation system."""

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VISIBLYAI_API_KEY = os.getenv("VISIBLYAI_API_KEY")
VISIBLYAI_BASE_URL = os.getenv("VISIBLYAI_BASE_URL", "https://www.antonioblago.com/api/v1/mcp")
BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")

# YouTube
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")

# Blog
BLOG_LANGUAGE = os.getenv("BLOG_LANGUAGE", "de")

# WordPress
WORDPRESS_URL = os.getenv("WORDPRESS_URL")
WORDPRESS_USER = os.getenv("WORDPRESS_USER")
WORDPRESS_APP_PASSWORD = os.getenv("WORDPRESS_APP_PASSWORD")

# Claude model to use for content generation
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Output directory
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
