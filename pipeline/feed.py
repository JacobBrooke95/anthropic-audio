"""Apple-Podcasts-ready RSS 2.0 feed with itunes + podcast namespaces."""
from __future__ import annotations
import hashlib
import html as H
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from .config import DOCS, PODCAST, SITE_URL, FEED_URL, SOURCES
from .util import rfc2822, parse_iso


def _art_url(slug: str) -> str:
    """Episode art URL with a content-hash query so podcast apps refetch re-rendered art."""
    url = f"{SITE_URL}/art/{slug}.jpg"
    f = DOCS / "art" / f"{slug}.jpg"
    if f.exists():
        url += "?v=" + hashlib.sha1(f.read_bytes()).hexdigest()[:8]
    return url


def _cdata(s: str) -> str:
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def show_notes_html(ep: dict) -> str:
    src = SOURCES[ep["source"]]
    parts = []
    if ep.get("subtitle"):
        parts.append(f"<p>{H.escape(ep['subtitle'])}</p>")
    meta = f"<p><strong>Source:</strong> <a href=\"{H.escape(ep['url'])}\">{H.escape(ep['url'])}</a><br/>"
    meta += f"<strong>Published:</strong> {parse_iso(ep['date']).strftime('%B %-d, %Y')} · {H.escape(src['name'])}"
    if ep.get("authors"):
        meta += f"<br/><strong>Authors:</strong> {H.escape(', '.join(ep['authors']))}"
    if ep.get("category"):
        meta += f"<br/><strong>Category:</strong> {H.escape(ep['category'])}"
    meta += f"<br/><strong>Length:</strong> {ep.get('word_count', 0):,} words · {_mmss(ep['duration'])}</p>"
    parts.append(meta)
    if ep.get("links"):
        items = "".join(f"<li><a href=\"{H.escape(l['href'])}\">{H.escape(l['text'] or l['href'])}</a></li>" for l in ep["links"][:60])
        parts.append(f"<p><strong>Links referenced in the post:</strong></p><ul>{items}</ul>")
    parts.append(f"<p><a href=\"{SITE_URL}/episodes/{ep['slug']}/\">Full text copy, transcript, and player</a> on the episode page.</p>")
    parts.append("<p><em>Unofficial audio edition generated automatically with Kokoro text-to-speech. "
                 "Post content © Anthropic, PBC; this feed is not affiliated with or endorsed by Anthropic.</em></p>")
    return "".join(parts)


def show_notes_text(ep: dict, limit: int = 3900) -> str:
    src = SOURCES[ep["source"]]
    lines = []
    if ep.get("subtitle"):
        lines.append(ep["subtitle"]); lines.append("")
    lines.append(f"Source: {ep['url']}")
    lines.append(f"Published {parse_iso(ep['date']).strftime('%B %-d, %Y')} · {src['name']}" + (f" · by {', '.join(ep['authors'])}" if ep.get("authors") else ""))
    lines.append("")
    if ep.get("links"):
        lines.append("Links referenced in the post:")
        for l in ep["links"][:40]:
            lines.append(f"• {l['text'] or l['href']}: {l['href']}")
        lines.append("")
    lines.append(f"Full text + transcript: {SITE_URL}/episodes/{ep['slug']}/")
    lines.append("Unofficial audio edition, generated automatically. Post content © Anthropic, PBC.")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _mmss(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m} min"


def build_feed(episodes: list[dict]) -> str:
    P = PODCAST
    now = datetime.now(timezone.utc)
    eps = sorted(episodes, key=lambda e: e["date"], reverse=True)
    cats = ""
    for cat, sub in P["categories"]:
        if sub:
            cats += f'    <itunes:category text="{escape(cat)}"><itunes:category text="{escape(sub)}"/></itunes:category>\n'
        else:
            cats += f'    <itunes:category text="{escape(cat)}"/>\n'
    cover = f"{SITE_URL}/{P['cover_file']}"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0">',
        "  <channel>",
        f"    <title>{escape(P['title'])}</title>",
        f"    <link>{SITE_URL}/</link>",
        f'    <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>',
        f"    <description>{escape(P['description'])}</description>",
        f"    <language>{P['language']}</language>",
        f"    <copyright>{escape(P['copyright'])}</copyright>",
        f"    <lastBuildDate>{rfc2822(now)}</lastBuildDate>",
        f"    <pubDate>{rfc2822(parse_iso(eps[0]['date'])) if eps else rfc2822(now)}</pubDate>",
        "    <generator>anthropic-audio (https://github.com/JacobBrooke95/anthropic-audio)</generator>",
        f"    <itunes:author>{escape(P['author'])}</itunes:author>",
        f"    <itunes:subtitle>{escape(P['subtitle'])}</itunes:subtitle>",
        f"    <itunes:summary>{escape(P['description'])}</itunes:summary>",
        "    <itunes:owner>",
        f"      <itunes:name>{escape(P['owner_name'])}</itunes:name>",
        f"      <itunes:email>{escape(P['owner_email'])}</itunes:email>",
        "    </itunes:owner>",
        f'    <itunes:image href="{cover}"/>',
        f"    <image><url>{cover}</url><title>{escape(P['title'])}</title><link>{SITE_URL}/</link></image>",
        cats.rstrip("\n"),
        f"    <itunes:explicit>{'true' if P['explicit'] else 'false'}</itunes:explicit>",
        "    <itunes:type>episodic</itunes:type>",
        f"    <podcast:guid>{P['guid']}</podcast:guid>",
        "    <podcast:medium>podcast</podcast:medium>",
        "    <podcast:locked>no</podcast:locked>",
        '    <podcast:txt purpose="ai-content">Audio generated automatically with Kokoro text-to-speech from Anthropic\'s published posts.</podcast:txt>',
    ]
    for ep in eps:
        src = SOURCES[ep["source"]]
        title = f"{src['label']}: {ep['title']}"
        audio = f"{SITE_URL}/audio/{ep['slug']}.mp3"
        art = _art_url(ep["slug"])
        page = f"{SITE_URL}/episodes/{ep['slug']}/"
        out += [
            "    <item>",
            f"      <title>{escape(title)}</title>",
            f"      <itunes:title>{escape(title)}</itunes:title>",
            f"      <link>{page}</link>",
            f'      <guid isPermaLink="false">{escape(ep["url"])}</guid>',
            f"      <pubDate>{rfc2822(parse_iso(ep['date']))}</pubDate>",
            f"      <description>{escape(show_notes_text(ep))}</description>",
            f"      <content:encoded>{_cdata(show_notes_html(ep))}</content:encoded>",
            f'      <enclosure url="{audio}" length="{ep["bytes"]}" type="audio/mpeg"/>',
            f"      <itunes:duration>{int(round(ep['duration']))}</itunes:duration>",
            f'      <itunes:image href="{art}"/>',
            f'      <podcast:transcript url="{SITE_URL}/transcripts/{ep["slug"]}.vtt" type="text/vtt"/>',
            *([f'      <podcast:chapters url="{SITE_URL}/chapters/{ep["slug"]}.json" type="application/json+chapters"/>']
              if (DOCS / "chapters" / f"{ep['slug']}.json").exists() else []),
            f"      <itunes:author>{escape(', '.join(ep['authors']) if ep.get('authors') else 'Anthropic')}</itunes:author>",
            f"      <itunes:subtitle>{escape((ep.get('subtitle') or src['name'])[:250])}</itunes:subtitle>",
            f"      <itunes:summary>{escape(show_notes_text(ep))}</itunes:summary>",
            "      <itunes:explicit>false</itunes:explicit>",
            "      <itunes:episodeType>full</itunes:episodeType>",
            f"      <itunes:episode>{ep['episode']}</itunes:episode>",
            f'      <podcast:transcript url="{SITE_URL}/transcripts/{ep["slug"]}.vtt" type="text/vtt" language="en"/>',
            f'      <podcast:transcript url="{SITE_URL}/transcripts/{ep["slug"]}.txt" type="text/plain" language="en"/>',
            "    </item>",
        ]
    out += ["  </channel>", "</rss>", ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- text (full-post) feed

TEXT_FEED_FILE = "posts.xml"


def build_text_feed(episodes: list[dict], load_post) -> str:
    """Plain RSS 2.0 feed of the posts themselves (full HTML in content:encoded) for feed readers.
    `load_post(ep)` returns the stored Post (or None)."""
    from .site import render_blocks_html
    P = PODCAST
    now = datetime.now(timezone.utc)
    eps = sorted(episodes, key=lambda e: e["date"], reverse=True)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:webfeeds="http://webfeeds.org/rss/1.0">',
        "  <channel>",
        f"    <title>{escape(P['title'])} — full-text posts</title>",
        f"    <link>{SITE_URL}/</link>",
        f'    <atom:link href="{SITE_URL}/{TEXT_FEED_FILE}" rel="self" type="application/rss+xml"/>',
        "    <description>Unofficial full-text RSS feed of new posts on Anthropic's research blog, newsroom, and the Claude blog "
        "(which publish no RSS of their own). Each item carries the complete post and a link to its audio edition. "
        "Not affiliated with Anthropic; content © Anthropic, PBC.</description>",
        f"    <language>{P['language']}</language>",
        f"    <image><url>{SITE_URL}/icon.png</url><title>{escape(P['title'])} — full-text posts</title><link>{SITE_URL}/</link></image>",
        f"    <webfeeds:icon>{SITE_URL}/icon.png</webfeeds:icon>",
        f'    <webfeeds:cover image="{SITE_URL}/{P["cover_file"]}"/>',
        "    <webfeeds:accentColor>b5532e</webfeeds:accentColor>",
        f"    <lastBuildDate>{rfc2822(now)}</lastBuildDate>",
        "    <generator>anthropic-audio (https://github.com/JacobBrooke95/anthropic-audio)</generator>",
    ]
    for ep in eps:
        src = SOURCES[ep["source"]]
        post = load_post(ep)
        page = f"{SITE_URL}/episodes/{ep['slug']}/"
        audio = f"{SITE_URL}/audio/{ep['slug']}.mp3"
        body = render_blocks_html(post.blocks, img_prefix=f"{SITE_URL}/posts/{ep['slug']}/") if post else ""
        meta = (f"<p><em>{H.escape(src['name'])} · {parse_iso(ep['date']).strftime('%B %-d, %Y')}"
                + (f" · {H.escape(', '.join(ep['authors']))}" if ep.get("authors") else "") + "</em><br/>"
                f"Original: <a href=\"{H.escape(ep['url'])}\">{H.escape(ep['url'])}</a> · "
                f"<a href=\"{audio}\">Listen ({_mmss(ep['duration'])})</a> · <a href=\"{page}\">Episode page</a></p>")
        content = meta + (f"<p><strong>{H.escape(ep['subtitle'])}</strong></p>" if ep.get("subtitle") else "") + body + \
                  "<hr/><p><em>Unofficial copy for the audio edition. Content © Anthropic, PBC.</em></p>"
        out += [
            "    <item>",
            f"      <title>{escape(src['label'] + ': ' + ep['title'])}</title>",
            f"      <link>{escape(ep['url'])}</link>",
            f'      <guid isPermaLink="true">{escape(ep["url"])}</guid>',
            f"      <pubDate>{rfc2822(parse_iso(ep['date']))}</pubDate>",
            f"      <dc:creator>{escape(', '.join(ep['authors']) if ep.get('authors') else 'Anthropic')}</dc:creator>",
            f"      <category>{escape(src['name'])}</category>",
            f"      <description>{escape((ep.get('subtitle') or ep['title']) + ' — ' + src['name'] + '. Audio edition: ' + audio)}</description>",
            f"      <content:encoded>{_cdata(content)}</content:encoded>",
            "    </item>",
        ]
    out += ["  </channel>", "</rss>", ""]
    return "\n".join(out)
