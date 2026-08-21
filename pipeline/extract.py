"""Fetch a post and turn it into a structured Post (metadata + content blocks).

Blocks are plain dicts so they serialize to JSON and can be re-rendered later:
  {"type": "heading", "level": 2, "text": str, "html": str}
  {"type": "paragraph", "text": str, "html": str}
  {"type": "list", "ordered": bool, "items": [{"text","html"}]}
  {"type": "quote", "text": str, "html": str}
  {"type": "code", "text": str, "lang": str|None}
  {"type": "image", "src": str, "alt": str, "caption": str, "local": str|None}
  {"type": "table", "rows": [[str]], "html": str}
  {"type": "footnotes", "items": [{"n": str, "text": str, "html": str}]}
"""
from __future__ import annotations
import re, json, html as htmlmod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup, NavigableString, Tag
from .config import SOURCES
from .util import http_get, parse_iso, log

INLINE_KEEP = {"a", "em", "strong", "b", "i", "code", "sup", "sub", "br", "u", "s", "mark", "abbr", "kbd"}
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote", "pre", "figure", "table", "img", "hr"}
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December"


@dataclass
class Post:
    url: str
    source: str
    slug: str
    title: str
    subtitle: str
    date: str                       # ISO 8601 UTC publish time
    authors: list[str]
    category: str
    hero: str | None
    blocks: list[dict]
    links: list[dict] = field(default_factory=list)   # [{"text","href"}]
    word_count: int = 0
    fetched_at: str = ""

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Post(**d)


# ----------------------------------------------------------------------------- helpers

def _unwrap_img(src: str, base: str) -> str:
    src = urljoin(base, src)
    p = urlparse(src)
    if p.path.endswith("/_next/image"):
        inner = parse_qs(p.query).get("url")
        if inner:
            return unquote(inner[0])
    return src


def _best_img_src(img: Tag, base: str) -> str | None:
    for attr in ("src", "data-src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return _unwrap_img(v, base)
    ss = img.get("srcset") or img.get("data-srcset")
    if ss:
        cands = [c.strip().split(" ")[0] for c in ss.split(",") if c.strip()]
        if cands:
            return _unwrap_img(cands[-1], base)
    return None


def _clean_inline(node: Tag | NavigableString, base: str, links: list[dict]) -> str:
    """Serialize inline content to a minimal, safe HTML string (links/emphasis/code kept)."""
    if isinstance(node, NavigableString):
        if node.parent and node.parent.name in ("script", "style"):
            return ""
        return htmlmod.escape(str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name in ("script", "style", "button", "svg", "noscript"):
        return ""
    inner = "".join(_clean_inline(c, base, links) for c in node.children)
    if name == "br":
        return " "
    if name == "a":
        href = node.get("href")
        if href and not href.startswith(("#", "javascript:")):
            href = urljoin(base, href)
            txt = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if txt and not any(l["href"] == href for l in links):
                links.append({"text": txt, "href": href})
            return f'<a href="{htmlmod.escape(href)}">{inner}</a>'
        return inner
    if name in ("em", "i"):
        return f"<em>{inner}</em>"
    if name in ("strong", "b"):
        return f"<strong>{inner}</strong>"
    if name == "code":
        return f"<code>{inner}</code>"
    if name in ("sup", "sub"):
        return f"<{name}>{inner}</{name}>"
    if name in ("img",):
        return ""
    return inner


def _text_of(html_fragment: str) -> str:
    t = BeautifulSoup(html_fragment, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", t).strip()


# ----------------------------------------------------------------------------- block walker

class _Walker:
    def __init__(self, base: str):
        self.base = base
        self.blocks: list[dict] = []
        self.links: list[dict] = []

    def walk(self, el: Tag):
        for child in el.children:
            if isinstance(child, NavigableString):
                txt = str(child).strip()
                if txt:
                    self._para_from_html(htmlmod.escape(txt))
                continue
            if not isinstance(child, Tag):
                continue
            self.handle(child)

    def handle(self, el: Tag):
        name = el.name.lower()
        cls = " ".join(el.get("class") or [])
        if name in ("script", "style", "button", "nav", "form", "svg", "noscript", "iframe", "video"):
            return
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            html_ = _clean_inline(el, self.base, self.links)
            text = _text_of(html_)
            if text:
                self.blocks.append({"type": "heading", "level": int(name[1]), "text": text, "html": html_})
        elif name == "p":
            html_ = _clean_inline(el, self.base, self.links)
            if el.find("img"):
                for img in el.find_all("img"):
                    self._image(img, caption="")
            if _text_of(html_):
                kind = "footnote" if "footnote" in cls else "paragraph"
                self.blocks.append({"type": kind, "text": _text_of(html_), "html": html_})
        elif name in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                # nested lists: flatten with " — " separators
                html_ = _clean_inline(li, self.base, self.links)
                text = _text_of(html_)
                if text:
                    items.append({"text": text, "html": html_})
            if items:
                self.blocks.append({"type": "list", "ordered": name == "ol", "items": items})
        elif name == "blockquote":
            html_ = "".join(_clean_inline(c, self.base, self.links) if not (isinstance(c, Tag) and c.name == "p") else "<p>" + _clean_inline(c, self.base, self.links) + "</p>" for c in el.children)
            text = _text_of(html_)
            if text:
                self.blocks.append({"type": "quote", "text": text, "html": html_})
        elif name == "pre":
            code = el.get_text("\n").strip("\n")
            lang = None
            c = el.find("code")
            if c:
                m = re.search(r"language-([\w+-]+)", " ".join(c.get("class") or []))
                lang = m.group(1) if m else None
            if code.strip():
                self.blocks.append({"type": "code", "text": code, "lang": lang})
        elif name == "figure":
            cap = el.find("figcaption")
            caption = _text_of(_clean_inline(cap, self.base, self.links)) if cap else ""
            imgs = el.find_all("img")
            if imgs:
                self._image(imgs[0], caption)
            elif el.find("table"):
                self._table(el.find("table"), caption)
            elif el.find("pre"):
                self.handle(el.find("pre"))
            else:
                # figure without image (video/embed): keep the caption as a note
                if caption:
                    self.blocks.append({"type": "paragraph", "text": caption, "html": htmlmod.escape(caption)})
        elif name == "img":
            self._image(el, "")
        elif name == "table":
            self._table(el, "")
        elif name == "hr":
            pass
        else:
            # div/section/span/etc: descend
            if el.find(list(BLOCK_TAGS)):
                self.walk(el)
            else:
                html_ = _clean_inline(el, self.base, self.links)
                self._para_from_html(html_)

    def _para_from_html(self, html_: str):
        text = _text_of(html_)
        if text:
            self.blocks.append({"type": "paragraph", "text": text, "html": html_})

    def _image(self, img: Tag, caption: str):
        src = _best_img_src(img, self.base)
        if not src:
            return
        alt = (img.get("alt") or "").strip()
        if self.blocks and self.blocks[-1].get("type") == "image" and self.blocks[-1]["src"] == src:
            if caption and not self.blocks[-1]["caption"]:
                self.blocks[-1]["caption"] = caption
            return
        self.blocks.append({"type": "image", "src": src, "alt": alt, "caption": caption, "local": None})

    def _table(self, tbl: Tag, caption: str):
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if rows:
            html_rows = "".join("<tr>" + "".join(f"<td>{htmlmod.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
            self.blocks.append({"type": "table", "rows": rows, "caption": caption, "html": f"<table>{html_rows}</table>"})


# ----------------------------------------------------------------------------- site adapters

def _visible_date(text: str) -> datetime | None:
    m = re.search(rf"\b({MONTHS})\.? (\d{{1,2}}), (\d{{4}})\b", text)
    if not m:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y"):
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}, {m.group(3)}", fmt).replace(hour=16, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return tag.get("content") if tag else None


def _anthropic(soup: BeautifulSoup, html: str, url: str) -> dict:
    body = soup.find("div", class_=re.compile(r"Body-module.*__body(\s|$)"))
    if body is None:
        # fallback: the element with the most direct <p> children inside <article>
        art = soup.find("article") or soup
        body = max(art.find_all(["div", "section"]), key=lambda e: len(e.find_all("p", recursive=False)), default=None)
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (_meta(soup, "og:title") or "")
    hero_wrap = soup.find("div", class_=re.compile(r"PostDetail.*__header")) or soup.find("div", class_=re.compile(r"PostDetail.*__hero"))
    header_text = hero_wrap.get_text(" ", strip=True) if hero_wrap else ""
    category = ""
    subj = soup.find(class_=re.compile(r"PostDetail.*__subjects"))
    if subj:
        category = subj.get_text(" ", strip=True)
    # publish time from RSC payload; verify against the visible date
    vis = _visible_date(header_text) or _visible_date(soup.get_text(" ")[:4000])
    date = None
    for m in re.finditer(r'publishedOn\\?":\\?"([0-9T:.+\-Z]+)', html):
        try:
            cand = parse_iso(m.group(1))
        except ValueError:
            continue
        if vis is None or cand.date() == vis.date():
            date = cand
            break
    if date is None:
        date = vis
    # authors: first footnote-styled paragraph at the very top of the body
    authors: list[str] = []
    if body is not None:
        first = body.find(["p", "h2", "h3", "ul", "div", "figure"], recursive=False)
        if first is not None and first.name == "p" and "footnote" in " ".join(first.get("class") or []):
            txt = first.get_text(" ", strip=True)
            if len(txt) < 400 and not txt.endswith(".") or re.match(r"^[A-Z][\w.’'\-]+(\s[A-Z][\w.’'\-]+)+", txt):
                authors = [re.sub(r"^(and|&)\s+", "", a.strip()) for a in re.split(r",\s*|\s+and\s+|&", txt.replace("\xa0", " ")) if a.strip()]
                authors = [a for a in authors if a]
                first.decompose()
    return {"body": body, "title": title, "subtitle": _meta(soup, "og:description") or "", "date": date,
            "authors": authors, "category": category, "hero": _meta(soup, "og:image")}


def _claude(soup: BeautifulSoup, html: str, url: str) -> dict:
    body = soup.find("div", class_="u-rich-text-blog") or soup.find("div", class_="w-richtext")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        title = re.sub(r"\s*\|\s*Claude.*$", "", _meta(soup, "og:title") or "")
    date = None
    ld = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "")
            ld.extend(d if isinstance(d, list) else [d])
        except Exception:
            pass
    for d in ld:
        if isinstance(d, dict) and d.get("@type") in ("BlogPosting", "Article", "NewsArticle") and d.get("datePublished"):
            dp = d["datePublished"]
            try:
                date = parse_iso(dp)
            except ValueError:
                date = _visible_date(dp)
            break
    if date is None:
        t = soup.find("time")
        if t and t.get("datetime"):
            try:
                date = parse_iso(t["datetime"])
            except ValueError:
                pass
    if date is None:
        date = _visible_date(soup.get_text(" ")[:6000])
    # subtitle: first <p> in the hero that isn't in body, or og:description
    subtitle = _meta(soup, "og:description") or ""
    return {"body": body, "title": title, "subtitle": subtitle, "date": date, "authors": [],
            "category": "", "hero": _meta(soup, "og:image")}


ADAPTERS = {"anthropic": _anthropic, "claude": _claude}


# ----------------------------------------------------------------------------- public API

def extract(url: str, source: str, html: str | None = None) -> Post:
    src = SOURCES[source]
    html = html or http_get(url)
    soup = BeautifulSoup(html, "lxml")
    info = ADAPTERS[src["site"]](soup, html, url)
    body = info["body"]
    if body is None:
        raise RuntimeError("could not locate article body")
    w = _Walker(url)
    w.walk(body)
    blocks = w.blocks
    # fold footnote paragraphs at the end into one footnotes block
    fns = [b for b in blocks if b["type"] == "footnote"]
    blocks = [b for b in blocks if b["type"] != "footnote"]
    if fns:
        items = []
        for i, b in enumerate(fns, 1):
            m = re.match(r"^\s*(\d+)[.)]?\s+(.*)$", b["text"])
            items.append({"n": m.group(1) if m else str(i), "text": m.group(2) if m else b["text"], "html": b["html"]})
        blocks.append({"type": "footnotes", "items": items})
    text_len = sum(len(b.get("text", "")) for b in blocks) + sum(len(i["text"]) for b in blocks if b["type"] == "list" for i in b["items"])
    if text_len < 300:
        raise RuntimeError(f"article body too short ({text_len} chars) — extraction probably failed")
    if not info["date"]:
        raise RuntimeError("could not determine publish date")
    words = sum(len(b.get("text", "").split()) for b in blocks) + sum(len(i["text"].split()) for b in blocks if b["type"] == "list" for i in b["items"])
    path_slug = urlparse(url).path.rstrip("/").split("/")[-1]
    from .util import slugify, iso_now
    slug = f"{source}-{info['date'].date().isoformat()}-{slugify(path_slug, 60)}"
    return Post(url=url, source=source, slug=slug, title=info["title"].strip(), subtitle=(info["subtitle"] or "").strip(),
                date=info["date"].astimezone(timezone.utc).isoformat(), authors=info["authors"], category=info["category"],
                hero=info["hero"], blocks=blocks, links=w.links, word_count=words, fetched_at=iso_now())
