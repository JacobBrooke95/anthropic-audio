"""Central configuration. Edit this file to rebrand / repoint the feed."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"            # GitHub Pages publishes this directory
STATE_FILE = ROOT / "state" / "episodes.json"
MODELS = ROOT / "models"
FONTS = ROOT / "assets" / "fonts"

# ---- Where the site lives -------------------------------------------------
GITHUB_USER = "JacobBrooke95"
REPO_NAME = "anthropic-audio"
SITE_URL = f"https://{GITHUB_USER.lower()}.github.io/{REPO_NAME}"
FEED_URL = f"{SITE_URL}/feed.xml"

# ---- Podcast metadata -----------------------------------------------------
PODCAST = {
    "title": "Anthropic, Read Aloud",
    "subtitle": "Unofficial audio editions of Anthropic's research, news, and Claude blog posts",
    "description": (
        "Unofficial, automatically generated audio versions of posts from Anthropic's "
        "research blog (anthropic.com/research), newsroom (anthropic.com/news), and the "
        "Claude blog (claude.com/blog). Each episode is a complete, faithful reading of one "
        "post, published within an hour of the original during Pacific business hours. "
        "Show notes carry the source link and every link referenced in the post. "
        "Not affiliated with or endorsed by Anthropic; all post content is the property of Anthropic, PBC."
    ),
    "author": "Jacob Brooke",
    "owner_name": "Jacob Brooke",
    "owner_email": "jacob.brooke95@gmail.com",
    "language": "en-us",
    "copyright": "Post content © Anthropic, PBC. Audio edition assembled by Jacob Brooke.",
    "categories": [("Technology", None), ("Science", None), ("News", "Tech News")],
    "explicit": False,
    # stable UUID for podcast:guid (generated once; do not change)
    "guid": "5c0c0a9e-3c0e-5b51-9c4a-4f2c3c7c6b7a",
    "cover_file": "cover.jpg",
}

# ---- Sources ----------------------------------------------------------------
SOURCES = {
    "research": {
        "label": "Research",
        "name": "Anthropic Research",
        "home": "https://www.anthropic.com/research",
        "sitemap": "https://www.anthropic.com/sitemap.xml",
        "prefix": "https://www.anthropic.com/research/",
        "listing": "https://www.anthropic.com/research",
        "site": "anthropic",
    },
    "news": {
        "label": "News",
        "name": "Anthropic Newsroom",
        "home": "https://www.anthropic.com/news",
        "sitemap": "https://www.anthropic.com/sitemap.xml",
        "prefix": "https://www.anthropic.com/news/",
        "listing": "https://www.anthropic.com/news",
        "site": "anthropic",
    },
    "claude-blog": {
        "label": "Claude Blog",
        "name": "Claude Blog",
        "home": "https://claude.com/blog",
        "sitemap": "https://claude.com/sitemap.xml",
        "prefix": "https://claude.com/blog/",
        "listing": "https://claude.com/blog",
        "site": "claude",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36 anthropic-audio/1.0 (+%s)" % SITE_URL
)

# ---- TTS --------------------------------------------------------------------
TTS = {
    "model": MODELS / "kokoro-v1.0.int8.onnx",
    "voices": MODELS / "voices-v1.0.bin",
    "voice": "af_heart",
    "speed": 1.0,
    "lang": "en-us",
    "max_chunk_chars": 380,       # sentence-grouped chunk size fed to Kokoro
    "mp3_bitrate": "64k",         # mono speech; ~0.5 MB/min
    "mp3_rate": 44100,
    "pause": {"sentence": 0.12, "paragraph": 0.45, "heading_before": 0.8, "heading_after": 0.45, "section": 1.0},
    # read code blocks verbatim only if they are this short (lines); else summarize
    "max_code_lines_read": 3,
}

# ---- Intro music -------------------------------------------------------------
MUSIC = {
    "enabled": True,   # mix the deterministic intro bed (pipeline/music.py) into new episodes
    "solo": 2.5,       # seconds of music alone before the speech timeline starts (VTT cues shift by this)
    "limit": 0.89,     # post-mix peak ceiling (~ -1 dBFS) so the encoded MP3 cannot clip
}

# ---- Run policy ---------------------------------------------------------------
MAX_PER_RUN = 3          # safety valve: episodes generated per invocation
MAX_RETRIES = 3          # failed posts are retried on later runs up to this many times
