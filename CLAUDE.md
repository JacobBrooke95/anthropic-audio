# CLAUDE.md — anthropic-audio

Automated podcast: every new post on anthropic.com/research, anthropic.com/news and claude.com/blog
→ full-length Kokoro-TTS MP3 + episode art + show notes + transcript + full-text copy → GitHub Pages
(`docs/`) + Apple-ready RSS (`docs/feed.xml`). Hourly GitHub Actions cron (PT business hours).
Read README.md for the architecture and commands.

Invariants:
- Never commit `models/` (Kokoro ONNX, ~120 MB) — `scripts/fetch-models.sh` downloads it; Actions caches it.
- `state/episodes.json` is the source of truth for what has been seen/published; `docs/posts/<slug>/post.json`
  is the structured copy used by `rebuild`. Never hand-edit `docs/feed.xml` — regenerate with `rebuild`.
- Episode GUID = original post URL. Re-running `add <url>` re-renders in place (same slug if same publish date).
- Always validate: `uv run python scripts/validate_feed.py docs/feed.xml` (CI does this before committing).
- Multiprocessing uses *spawn*: any new entry point must be guarded by `if __name__ == "__main__":`.
- Commit author email must be the GitHub noreply address (email privacy is on for this account).
