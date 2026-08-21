"""Static site: index, one page per episode (player + show notes + full post copy), markdown copies."""
from __future__ import annotations
import html as H
import re, shutil
from pathlib import Path
from urllib.parse import urlparse
from .config import DOCS, PODCAST, SITE_URL, FEED_URL, SOURCES, ROOT
from .util import parse_iso, http_get, log, hms

CSS = """
:root{--bg:#faf7f2;--fg:#1d1d1f;--muted:#6b6b70;--accent:#b5532e;--card:#fff;--line:#e6e1d8;--code:#f1ede6}
@media(prefers-color-scheme:dark){:root{--bg:#15171b;--fg:#ecebe7;--muted:#a0a0a6;--accent:#e39a6c;--card:#1d2026;--line:#2c3037;--code:#23262d}}
*{box-sizing:border-box}body{margin:0;font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--accent)}header.site{padding:2rem 1rem 1rem;max-width:860px;margin:0 auto}header.site h1{margin:0;font-size:2rem}
header.site p{color:var(--muted);margin:.3rem 0}main{max-width:860px;margin:0 auto;padding:0 1rem 4rem}
.subscribe{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1rem 1.2rem;margin:1rem 0 2rem}
.subscribe code{background:var(--code);padding:.15rem .4rem;border-radius:6px;word-break:break-all}
.subscribe .btns a{display:inline-block;margin:.4rem .5rem 0 0;padding:.45rem .8rem;border:1px solid var(--line);border-radius:8px;text-decoration:none;background:var(--bg)}
.ep{display:flex;gap:1rem;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1rem;margin:1rem 0}
.ep img{width:120px;height:120px;border-radius:8px;object-fit:cover;flex:none}.ep h2{margin:0 0 .3rem;font-size:1.2rem}
.badge{display:inline-block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:.1rem .5rem;border-radius:999px;background:var(--code);color:var(--muted);margin-right:.4rem}
.meta{color:var(--muted);font-size:.9rem}audio{width:100%;margin:.6rem 0}
article.post{margin-top:2rem;border-top:1px solid var(--line);padding-top:1.5rem}article.post img{max-width:100%;height:auto;border-radius:8px}
article.post figure{margin:1.5rem 0}article.post figcaption{font-size:.9rem;color:var(--muted)}article.post pre{background:var(--code);padding:1rem;border-radius:8px;overflow-x:auto;font-size:.85rem}
article.post code{background:var(--code);padding:.1rem .3rem;border-radius:4px;font-size:.9em}article.post blockquote{border-left:3px solid var(--accent);margin:1rem 0;padding:.2rem 1rem;color:var(--muted)}
article.post table{border-collapse:collapse;width:100%;font-size:.9rem;overflow-x:auto;display:block}article.post td,article.post th{border:1px solid var(--line);padding:.4rem .6rem;vertical-align:top}
.notes ul{padding-left:1.2rem}.hero{width:100%;border-radius:12px;margin:1rem 0}details summary{cursor:pointer;color:var(--accent)}
footer{max-width:860px;margin:0 auto;padding:2rem 1rem;color:var(--muted);font-size:.85rem}.small{font-size:.85rem}
"""


def _layout(title: str, body: str, *, depth: int = 0, extra_head: str = "") -> str:
    rel = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(title)}</title>
<link rel="alternate" type="application/rss+xml" title="{H.escape(PODCAST['title'])}" href="{FEED_URL}">
<link rel="stylesheet" href="{rel}style.css">{extra_head}
</head><body>
<header class="site"><h1><a href="{rel}" style="text-decoration:none;color:inherit">{H.escape(PODCAST['title'])}</a></h1>
<p>{H.escape(PODCAST['subtitle'])}</p></header>
<main>{body}</main>
<footer>Unofficial. Post content © Anthropic, PBC — copied here for the audio edition with links back to the originals. Audio generated automatically with Kokoro TTS. Not affiliated with or endorsed by Anthropic. <a href="https://github.com/JacobBrooke95/anthropic-audio">Source &amp; pipeline on GitHub</a>.</footer>
</body></html>"""


def _subscribe_box() -> str:
    feed = FEED_URL
    return f"""<div class="subscribe"><strong>Subscribe</strong> — feed URL: <code>{feed}</code>
<div class="btns"><a href="podcast://{feed.replace('https://','')}">Apple Podcasts</a>
<a href="https://overcast.fm/itunes?url={feed}" title="Overcast">Overcast</a>
<a href="pktc://subscribe/{feed.replace('https://','')}">Pocket Casts</a>
<a href="{feed}">Raw RSS</a></div>
<p class="small" style="margin:.6rem 0 0">New episodes appear within about an hour of a new post during Pacific business hours (Mon–Fri, 8am–6pm PT). Sources: <a href="https://www.anthropic.com/research">Research</a> · <a href="https://www.anthropic.com/news">News</a> · <a href="https://claude.com/blog">Claude Blog</a>.</p></div>"""


def render_blocks_html(blocks: list[dict], img_prefix: str = "") -> str:
    out = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            lvl = min(max(b["level"], 2), 4)
            out.append(f"<h{lvl}>{b['html']}</h{lvl}>")
        elif t == "paragraph":
            out.append(f"<p>{b['html']}</p>")
        elif t == "list":
            tag = "ol" if b["ordered"] else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{i['html']}</li>" for i in b["items"]) + f"</{tag}>")
        elif t == "quote":
            out.append(f"<blockquote>{b['html']}</blockquote>")
        elif t == "code":
            out.append(f"<pre><code>{H.escape(b['text'])}</code></pre>")
        elif t == "image":
            src = (img_prefix + b["local"]) if b.get("local") else b["src"]
            cap = f"<figcaption>{H.escape(b['caption'])}</figcaption>" if b.get("caption") else ""
            out.append(f'<figure><img src="{H.escape(src)}" alt="{H.escape(b.get("alt") or "")}" loading="lazy">{cap}</figure>')
        elif t == "table":
            cap = f"<figcaption>{H.escape(b['caption'])}</figcaption>" if b.get("caption") else ""
            out.append(f"<figure>{b['html']}{cap}</figure>")
        elif t == "footnotes":
            out.append("<h3>Footnotes</h3><ol>" + "".join(f"<li>{i['html']}</li>" for i in b["items"]) + "</ol>")
    return "\n".join(out)


def render_blocks_md(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        t = b["type"]
        if t == "heading":
            out.append("#" * min(max(b["level"], 2), 4) + " " + b["text"])
        elif t == "paragraph":
            out.append(_md_inline(b["html"]))
        elif t == "list":
            out.append("\n".join((f"{n}. " if b["ordered"] else "- ") + _md_inline(i["html"]) for n, i in enumerate(b["items"], 1)))
        elif t == "quote":
            out.append("> " + _md_inline(b["html"]).replace("\n", "\n> "))
        elif t == "code":
            out.append(f"```{b.get('lang') or ''}\n{b['text']}\n```")
        elif t == "image":
            out.append(f"![{b.get('alt') or ''}]({b['src']})" + (f"\n\n*{b['caption']}*" if b.get("caption") else ""))
        elif t == "table":
            rows = b["rows"]
            if rows:
                w = max(len(r) for r in rows)
                rows = [r + [""] * (w - len(r)) for r in rows]
                md = "| " + " | ".join(rows[0]) + " |\n|" + "---|" * w + "\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
                out.append(md)
        elif t == "footnotes":
            out.append("\n".join(f"[^{i['n']}]: {_md_inline(i['html'])}" for i in b["items"]))
    return "\n\n".join(out)


def _md_inline(html_: str) -> str:
    s = html_
    s = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", s, flags=re.S)
    s = re.sub(r"</?(em)>", "*", s); s = re.sub(r"</?(strong)>", "**", s); s = re.sub(r"</?code>", "`", s)
    s = re.sub(r"<[^>]+>", "", s)
    return H.unescape(s)


def localize_images(post, post_dir: Path, max_images: int = 60) -> None:
    """Download the post's images into docs/posts/<slug>/img/ so the copy is self-contained."""
    imgdir = post_dir / "img"
    n = 0
    for b in post.blocks:
        if b["type"] != "image" or b.get("local"):
            continue
        if n >= max_images:
            break
        n += 1
        src = b["src"]
        ext = (Path(urlparse(src).path).suffix or ".jpg").lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
            ext = ".jpg"
        name = f"{n:02d}{ext}"
        try:
            u = src + ("&" if "?" in src else "?") + "w=1600&auto=format" if "cdn.sanity.io" in src or "www-cdn.anthropic.com" in src else src
            data = http_get(u, binary=True)
            imgdir.mkdir(parents=True, exist_ok=True)
            (imgdir / name).write_bytes(data)
            b["local"] = f"img/{name}"
        except Exception as e:
            log.warning("image download failed %s: %s", src, e)


def write_episode_assets(post, ep: dict, transcript_txt: str) -> None:
    """Write per-episode HTML page, markdown copy, transcript text."""
    from .feed import show_notes_html
    src = SOURCES[post.source]
    pdir = DOCS / "posts" / post.slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "post.json").write_text(__import__("json").dumps(post.to_dict(), indent=1, ensure_ascii=False))
    md = f"# {post.title}\n\n" + (f"*{post.subtitle}*\n\n" if post.subtitle else "") + \
         f"Source: {post.url}  \nPublished: {post.date[:10]} · {src['name']}" + (f" · {', '.join(post.authors)}" if post.authors else "") + \
         "\n\n---\n\n" + render_blocks_md(post.blocks) + "\n"
    (pdir / "post.md").write_text(md)
    (DOCS / "transcripts").mkdir(parents=True, exist_ok=True)
    (DOCS / "transcripts" / f"{post.slug}.txt").write_text(transcript_txt)
    # episode page
    edir = DOCS / "episodes" / post.slug
    edir.mkdir(parents=True, exist_ok=True)
    body_html = render_blocks_html(post.blocks, img_prefix=f"../../posts/{post.slug}/")
    page = f"""
<p><span class="badge">{H.escape(src['label'])}</span><span class="meta">{parse_iso(post.date).strftime('%B %-d, %Y')}{' · ' + H.escape(', '.join(post.authors)) if post.authors else ''} · {hms(ep['duration'])} · {post.word_count:,} words</span></p>
<h1 style="margin:.2rem 0 .6rem">{H.escape(post.title)}</h1>
<img class="hero" src="../../art/{post.slug}.jpg" alt="Episode artwork" style="max-width:360px">
<audio controls preload="none" src="../../audio/{post.slug}.mp3"></audio>
<p class="small"><a href="../../audio/{post.slug}.mp3">Download MP3</a> · <a href="../../transcripts/{post.slug}.vtt">Transcript (VTT)</a> · <a href="../../transcripts/{post.slug}.txt">Transcript (text)</a> · <a href="../../posts/{post.slug}/post.md">Markdown copy</a> · <a href="{H.escape(post.url)}">Original post ↗</a></p>
<div class="notes">{show_notes_html(ep)}</div>
<article class="post"><h2 style="margin-top:0">Full text of the post</h2>
<p class="meta">Copied from <a href="{H.escape(post.url)}">{H.escape(post.url)}</a> on {post.fetched_at[:10]} for the audio edition. © Anthropic, PBC.</p>
{body_html}
</article>"""
    (edir / "index.html").write_text(_layout(f"{post.title} — {PODCAST['title']}", page, depth=2))


def write_index(episodes: list[dict]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "style.css").write_text(CSS)
    (DOCS / ".nojekyll").write_text("")
    eps = sorted(episodes, key=lambda e: e["date"], reverse=True)
    cards = []
    for ep in eps:
        src = SOURCES[ep["source"]]
        cards.append(f"""<div class="ep"><a href="episodes/{ep['slug']}/"><img src="art/{ep['slug']}.jpg" alt=""></a><div style="flex:1;min-width:0">
<span class="badge">{H.escape(src['label'])}</span><span class="meta">{parse_iso(ep['date']).strftime('%b %-d, %Y')} · {hms(ep['duration'])} · Ep. {ep['episode']}</span>
<h2><a href="episodes/{ep['slug']}/" style="text-decoration:none;color:inherit">{H.escape(ep['title'])}</a></h2>
<p class="meta" style="margin:.2rem 0 .4rem">{H.escape((ep.get('subtitle') or '')[:220])}</p>
<audio controls preload="none" src="audio/{ep['slug']}.mp3"></audio>
<p class="small" style="margin:0"><a href="{H.escape(ep['url'])}">Original ↗</a> · <a href="episodes/{ep['slug']}/">Show notes &amp; full text</a></p></div></div>""")
    body = _subscribe_box() + f"<p class='meta'>{len(eps)} episode{'s' if len(eps)!=1 else ''}</p>" + "\n".join(cards)
    (DOCS / "index.html").write_text(_layout(PODCAST["title"], body))
