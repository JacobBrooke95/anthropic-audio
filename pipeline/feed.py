"""Apple-Podcasts-ready RSS 2.0 feed with itunes + podcast namespaces."""
from __future__ import annotations
import html as H
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from .config import PODCAST, SITE_URL, FEED_URL, SOURCES
from .util import rfc2822, parse_iso


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
        art = f"{SITE_URL}/art/{ep['slug']}.jpg"
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
