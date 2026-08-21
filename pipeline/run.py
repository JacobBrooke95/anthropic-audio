"""CLI entry point.

  uv run python -m pipeline run [--max N] [--dry-run] [--since YYYY-MM-DD]
  uv run python -m pipeline add URL [URL...]         # force-process specific posts
  uv run python -m pipeline rebuild                    # regenerate site + feed from stored posts
  uv run python -m pipeline list                       # show episodes
"""
from __future__ import annotations
import argparse, logging, sys, time, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .config import DOCS, SOURCES, MAX_PER_RUN, MAX_RETRIES, PODCAST, TTS
from .util import log, parse_iso, iso_now
from .state import State
from .discover import discover
from .extract import extract, Post
from .speech import build_script, transcript_text
from .tts import synthesize, tag_mp3, write_vtt
from .artwork import episode_art, show_cover
from .site import write_episode_assets, write_index, localize_images
from .feed import build_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("phonemizer").setLevel(logging.ERROR)


def source_for(url: str) -> str | None:
    for k, s in SOURCES.items():
        if url.startswith(s["prefix"]):
            return k
    return None


def process(url: str, source: str, st: State, *, episode_no: int | None = None) -> dict:
    t0 = time.time()
    log.info("▶ %s", url)
    post = extract(url, source)
    log.info("  extracted: %r (%s) %d words, %d blocks, %d links", post.title, post.date[:10], post.word_count, len(post.blocks), len(post.links))
    segs = build_script(post)
    slug = post.slug
    mp3 = DOCS / "audio" / f"{slug}.mp3"
    art_path = DOCS / "art" / f"{slug}.jpg"
    art = episode_art(post, art_path)
    log.info("  artwork: %d bytes", len(art))
    res = synthesize(segs, mp3)
    log.info("  audio: %s, %.1f MB, %d chunks (%.0fs)", f"{res['duration']:.0f}s", res["bytes"] / 1e6, len(res["cues"]), time.time() - t0)
    existing = next((e for e in st.episodes if e["url"] == url), None)
    ep_no = episode_no or (existing["episode"] if existing else st.next_episode)
    tag_mp3(mp3, title=post.title, artist=", ".join(post.authors) or "Anthropic", album=PODCAST["title"], date=post.date,
            comment=post.url, art_jpeg=art, track=ep_no)
    res["bytes"] = mp3.stat().st_size
    write_vtt(res["cues"], DOCS / "transcripts" / f"{slug}.vtt")
    localize_images(post, DOCS / "posts" / slug)
    ep = {"slug": slug, "url": url, "source": source, "title": post.title, "subtitle": post.subtitle, "date": post.date,
          "authors": post.authors, "category": post.category, "links": post.links, "word_count": post.word_count,
          "duration": res["duration"], "bytes": res["bytes"], "episode": ep_no, "created": iso_now(), "hero": post.hero}
    write_episode_assets(post, ep, transcript_text(segs))
    st.add_episode(ep)
    if episode_no is None and not existing:
        st.next_episode = ep_no + 1
    st.mark(url, "published", slug=slug, episode=ep_no)
    st.save()
    log.info("✔ episode %d: %s (%.0fs total)", ep_no, slug, time.time() - t0)
    return ep


def rebuild(st: State):
    show_cover(DOCS / PODCAST["cover_file"])
    for ep in st.episodes:
        pj = DOCS / "posts" / ep["slug"] / "post.json"
        if pj.exists():
            import json
            post = Post.from_dict(json.loads(pj.read_text()))
            txt_path = DOCS / "transcripts" / f"{ep['slug']}.txt"
            write_episode_assets(post, ep, txt_path.read_text() if txt_path.exists() else "")
    write_index(st.episodes)
    (DOCS / "feed.xml").write_text(build_feed(st.episodes))
    log.info("site + feed rebuilt: %d episodes", len(st.episodes))


def cmd_run(args):
    st = State()
    found = discover()
    if st.baseline_date is None:
        # first run: only posts published on/after this date become episodes; everything older is marked skipped
        st.baseline_date = args.since or (datetime.now(timezone.utc) - timedelta(days=args.backfill_days)).date().isoformat()
        log.info("first run — baseline date set to %s", st.baseline_date)
    baseline = args.since or st.baseline_date
    new = [(u, m) for u, m in found.items() if st.status(u) not in ("published", "skipped")
           and (st.seen.get(u) or {}).get("attempts", 0) < MAX_RETRIES]
    # newest first by sitemap lastmod, unknown last
    new.sort(key=lambda x: x[1].get("lastmod") or "", reverse=True)
    log.info("%d unseen candidate(s)", len(new))
    done = 0
    for url, meta in new:
        if done >= args.max:
            log.info("max per run (%d) reached; remaining candidates wait for the next run", args.max)
            break
        # cheap pre-filter: sitemap lastmod older than baseline → certainly old; skip without fetching
        lm = meta.get("lastmod")
        if lm and lm[:10] < baseline:
            st.mark(url, "skipped", reason=f"lastmod {lm[:10]} < baseline {baseline}")
            continue
        if args.dry_run:
            log.info("would process %s (%s)", url, meta)
            continue
        try:
            post_date = None
            # fetch once to learn the true publish date before committing to TTS
            from .util import http_get
            html = http_get(url)
            post = extract(url, meta["source"], html)
            post_date = post.date[:10]
            if post_date < baseline:
                st.mark(url, "skipped", reason=f"published {post_date} < baseline {baseline}")
                st.save()
                continue
            process(url, meta["source"], st)
            done += 1
        except Exception as e:
            log.error("✖ %s: %s", url, e)
            log.debug(traceback.format_exc())
            st.mark(url, "failed", error=str(e)[:300])
            st.save()
    if not args.dry_run:
        rebuild(st)
    st.save()
    log.info("run complete: %d new episode(s)", done)


def cmd_add(args):
    st = State()
    for url in args.urls:
        src = source_for(url)
        if not src:
            log.error("unknown source for %s", url); continue
        try:
            process(url, src, st)
        except Exception as e:
            log.error("✖ %s: %s", url, e); log.debug(traceback.format_exc())
            st.mark(url, "failed", error=str(e)[:300]); st.save()
    rebuild(st)


def cmd_rebuild(args):
    rebuild(State())


def cmd_list(args):
    st = State()
    for ep in sorted(st.episodes, key=lambda e: e["date"]):
        print(f"{ep['episode']:3d}  {ep['date'][:10]}  {ep['source']:12s} {ep['duration']/60:5.1f}m  {ep['title']}")
    print(f"{len(st.episodes)} episodes; {sum(1 for v in st.seen.values() if v['status']=='skipped')} skipped; "
          f"{sum(1 for v in st.seen.values() if v['status']=='failed')} failed; baseline {st.baseline_date}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--max", type=int, default=MAX_PER_RUN); r.add_argument("--dry-run", action="store_true")
    r.add_argument("--since", help="override baseline date YYYY-MM-DD"); r.add_argument("--backfill-days", type=int, default=14)
    r.set_defaults(fn=cmd_run)
    a = sub.add_parser("add"); a.add_argument("urls", nargs="+"); a.set_defaults(fn=cmd_add)
    sub.add_parser("rebuild").set_defaults(fn=cmd_rebuild)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
