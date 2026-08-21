# Anthropic, Read Aloud — unofficial audio editions of Anthropic's posts

An automated pipeline that watches **anthropic.com/research**, **anthropic.com/news**, and
**claude.com/blog** once an hour during Pacific business hours, turns each new post into a
complete spoken-word MP3 (Kokoro TTS), builds square episode artwork from the post's hero
image, writes show notes with the source link and every link referenced in the post, and
publishes everything — audio, artwork, transcripts, a full-text copy of each post, and an
Apple-Podcasts-ready RSS feed — to GitHub Pages.

* **Site:** https://jacobbrooke95.github.io/anthropic-audio/
* **Feed:** https://jacobbrooke95.github.io/anthropic-audio/feed.xml

Not affiliated with or endorsed by Anthropic. Post content © Anthropic, PBC.

## How it works

```
GitHub Actions (hourly cron, PT business-hours guard)
 └─ uv run python -m pipeline run
     ├─ discover.py   sitemaps (anthropic.com, claude.com) + listing pages → candidate URLs
     ├─ extract.py    fetch post → title / date / authors / hero / structured blocks / links
     │                (anthropic.com: Next.js+Sanity markup, publishedOn from RSC payload;
     │                 claude.com: Webflow rich text + JSON-LD BlogPosting)
     ├─ speech.py     blocks → speech script (figures read by caption/alt, tables linearised,
     │                long code blocks summarised, footnotes at the end, TTS normalisation)
     ├─ tts.py        Kokoro-82M ONNX (CPU, multi-process) → loudness-normalised 64 kbps MP3,
     │                ID3 tags + embedded art, WebVTT transcript from per-chunk timings
     ├─ artwork.py    3000×3000 JPEG episode art from the post's og:image + show cover
     ├─ site.py       docs/: index, episode pages (player + show notes + full text), post.md/.json
     ├─ feed.py       docs/feed.xml (RSS 2.0 + itunes + podcast namespaces)
     └─ state.py      state/episodes.json (seen URLs, episode catalogue, baseline date)
 └─ scripts/validate_feed.py  → commit docs/ + state/ back to main → Pages redeploys
```

Only posts published on/after the **baseline date** (set on the first run; see `state/episodes.json`)
become episodes; older URLs are marked `skipped` once and never fetched again.
claude.com bulk-touches sitemap `lastmod`, so every candidate is fetched and its real publish date
checked before any TTS is spent.

## Run locally

```bash
uv sync
bash scripts/fetch-models.sh                 # Kokoro ONNX model + voices (~120 MB, not committed)
brew install ffmpeg                          # (ubuntu: apt-get install ffmpeg espeak-ng)

uv run python -m pipeline run --dry-run      # what would be processed
uv run python -m pipeline run --max 3        # discover + generate up to 3 episodes
uv run python -m pipeline add <post-url>     # force a specific post
uv run python -m pipeline rebuild            # regenerate site + feed from stored posts
uv run python -m pipeline list
uv run python scripts/validate_feed.py docs/feed.xml
python3 -m http.server -d docs 8000          # preview the site
```

`TTS_WORKERS` (default: half the cores, max 4) controls parallel synthesis.
Voice, speed, pauses, bitrate: `pipeline/config.py` (`TTS`). Feed metadata: `PODCAST` in the same file.

## Manual run on GitHub

Actions → **podcast** → *Run workflow*. Leave `urls` blank for normal discovery, or paste one or
more post URLs to force-process them (re-rendering an existing episode replaces it in place).

## Layout of `docs/` (the published site)

```
docs/
  index.html  feed.xml  cover.jpg  style.css  .nojekyll
  audio/<slug>.mp3          art/<slug>.jpg          transcripts/<slug>.{vtt,txt}
  episodes/<slug>/index.html                      # player + show notes + full post text
  posts/<slug>/{post.json,post.md,img/*}          # structured + markdown copy of the post
```

Slug = `<source>-<YYYY-MM-DD>-<post-path>`; episode GUID = the original post URL.
