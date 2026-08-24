"""Episode artwork (3000×3000 JPEG built from the post's hero image) and the show cover.

Anthropic and Claude hero illustrations sit on a flat background colour; when the hero's
edges are uniform the whole canvas is flooded with that exact colour and the hero placed
seamlessly, with text colours picked for contrast against it. Photographic heroes get a
full-bleed crop with a solid tinted text panel; posts with no usable hero fall back to a
per-source palette colour.
"""
from __future__ import annotations
import io
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .config import FONTS, SOURCES, PODCAST
from .util import http_get, log

SIZE = 3000
MARGIN = int(SIZE * 0.07)
PALETTE = {"research": (31, 64, 59), "news": (122, 52, 35), "claude-blog": (45, 52, 96)}  # fallback bg per source
CREAM = (244, 239, 230)
INK = (28, 26, 22)
ACCENT = (204, 120, 92)         # Anthropic "book cloth" rust
ACCENT_LIGHT = (224, 152, 122)  # same accent lifted for dark backgrounds
BOLD = FONTS / "DejaVuSans-Bold.ttf"
REG = FONTS / "DejaVuSans.ttf"


def _font(path: Path, size: int):
    return ImageFont.truetype(str(path), size)


def _fetch_image(url: str) -> Image.Image | None:
    try:
        # ask Sanity CDN for a reasonably sized render; other hosts ignore the query
        u = url + ("&" if "?" in url else "?") + "w=2400&auto=format" if "cdn.sanity.io" in url else url
        data = http_get(u, binary=True)
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            base = Image.new("RGBA", im.size, (255, 255, 255, 255))
            base.alpha_composite(im)
            im = base
        return ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:
        log.warning("hero fetch failed (%s): %s", url, e)
        return None


def _wrap(draw, text, font, max_w, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines and (len(" ".join(lines)) < len(text)):
        last = lines[-1]
        while draw.textlength(last + "…", font=font) > max_w and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last + "…"
    return lines


def _edge_color(hero: Image.Image) -> tuple[int, int, int] | None:
    """The hero's border colour if its edges are (near-)uniform, else None."""
    a = np.asarray(hero.resize((160, 160), Image.BILINEAR), dtype=np.float32)
    ring = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3),
                           a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    if ring.std(axis=0).max() < 12:
        return tuple(int(c) for c in ring.mean(axis=0))
    return None


def _luma(c) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _blend(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _human_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%B %-d, %Y")
    except ValueError:
        return iso[:10]


def _tracked_text(d, xy, text, font, fill, tracking=0):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking
    return x


def _waveform(d, x, y_base, fill, scale=1.0):
    """Small waveform mark (matches the site icon); returns its width."""
    heights, bar, gap = (58, 104, 156, 110, 72, 130, 84), 22, 14
    for h in heights:
        hh = int(h * scale)
        d.rounded_rectangle((x, y_base - hh, x + int(bar * scale), y_base), radius=int(11 * scale), fill=fill)
        x += int((bar + gap) * scale)
    return len(heights) * int((bar + gap) * scale)


def _fit_title(d, title, max_w, max_h):
    """Largest title size whose wrapped lines fit the box; prefers no truncation."""
    best = None
    for size in range(216, 108, -12):
        f = _font(BOLD, size)
        lines = _wrap(d, title, f, max_w, 4)
        line_h = int(size * 1.22)
        if len(lines) * line_h > max_h:
            continue
        truncated = lines and lines[-1].endswith("…")
        if not truncated:
            return f, lines, line_h
        if best is None:
            best = (f, lines, line_h)
    if best:
        return best
    f = _font(BOLD, 108)
    return f, _wrap(d, title, f, max_w, 4), int(108 * 1.22)


def _text_block(canvas, post, bg, top, bottom):
    """Eyebrow + title + footer, coloured for contrast against bg, centred in [top, bottom]."""
    d = ImageDraw.Draw(canvas)
    dark_bg = _luma(bg) < 140
    ink = CREAM if dark_bg else INK
    muted = _blend(ink, bg, 0.30)
    accent = ACCENT_LIGHT if dark_bg else (ACCENT if _luma(bg) > 200 else ink)
    max_w = SIZE - 2 * MARGIN

    f_eye = _font(BOLD, 66)
    eye_gap, rule_h, rule_gap = 84, 14, 56
    footer_h = 240
    avail = (bottom - footer_h) - top
    f_title, lines, line_h = _fit_title(d, post.title, max_w, avail - rule_h - rule_gap - 66 - eye_gap)
    block_h = rule_h + rule_gap + 66 + eye_gap + len(lines) * line_h
    y = top + max(0, (avail - block_h) // 2)

    d.rounded_rectangle((MARGIN, y, MARGIN + 260, y + rule_h), radius=rule_h // 2, fill=accent)
    y += rule_h + rule_gap
    eyebrow = f"{SOURCES[post.source]['name'].upper()}  ·  {_human_date(post.date).upper()}"
    _tracked_text(d, (MARGIN, y), eyebrow, f_eye, muted, tracking=6)
    y += 66 + eye_gap
    for ln in lines:
        d.text((MARGIN, y), ln, font=f_title, fill=ink)
        y += line_h

    f_foot = _font(REG, 56)
    foot_y = SIZE - 150
    d.text((MARGIN, foot_y - 56), f"{PODCAST['title']}  ·  unofficial audio edition", font=f_foot, fill=muted)
    _waveform(d, SIZE - MARGIN - 260, foot_y, accent)


def episode_art(post, out_path: Path) -> bytes:
    hero = _fetch_image(post.hero) if post.hero else None
    flat = _edge_color(hero) if hero is not None else None

    if hero is not None and flat is not None:
        # seamless: canvas in the hero's own background colour, hero laid in without a frame
        canvas = Image.new("RGB", (SIZE, SIZE), flat)
        fg = hero.copy()
        fg.thumbnail((SIZE, int(SIZE * 0.52)), Image.LANCZOS)
        y = max(120, (int(SIZE * 0.58) - fg.height) // 2)
        canvas.paste(fg, ((SIZE - fg.width) // 2, y))
        _text_block(canvas, post, flat, y + fg.height + int(SIZE * 0.03), SIZE)
    elif hero is not None:
        # photographic hero: full-bleed crop, solid tinted panel for the text
        canvas = ImageOps.fit(hero, (SIZE, SIZE), Image.LANCZOS)
        avg = tuple(int(c) for c in np.asarray(canvas.resize((8, 8))).reshape(-1, 3).mean(axis=0))
        panel = _blend(avg, (14, 14, 16), 0.78)
        panel_top = int(SIZE * 0.46)
        fade = 160
        for i in range(fade):
            t = i / fade
            row = canvas.crop((0, panel_top - fade + i, SIZE, panel_top - fade + i + 1))
            row = Image.blend(row, Image.new("RGB", (SIZE, 1), panel), t)
            canvas.paste(row, (0, panel_top - fade + i))
        ImageDraw.Draw(canvas).rectangle((0, panel_top, SIZE, SIZE), fill=panel)
        _text_block(canvas, post, panel, panel_top + int(SIZE * 0.03), SIZE)
    else:
        bg = PALETTE.get(post.source, (40, 40, 40))
        canvas = Image.new("RGB", (SIZE, SIZE), bg)
        d = ImageDraw.Draw(canvas)
        _waveform(d, MARGIN, int(SIZE * 0.30), _blend(bg, CREAM, 0.18), scale=6.0)
        _text_block(canvas, post, bg, int(SIZE * 0.38), SIZE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 82
    while True:
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() < 900_000 or quality <= 55:
            break
        quality -= 7
    data = buf.getvalue()
    out_path.write_bytes(data)
    return data


def show_cover(out_path: Path) -> None:
    canvas = Image.new("RGB", (SIZE, SIZE), (28, 31, 38))
    d = ImageDraw.Draw(canvas)
    # subtle stripes
    for i in range(0, SIZE, 120):
        d.line([(0, i), (SIZE, i + 400)], fill=(34, 38, 46), width=30)
    f_big = _font(BOLD, 300)
    f_mid = _font(BOLD, 135)
    f_small = _font(REG, 80)
    d.text((int(SIZE * 0.08), int(SIZE * 0.22)), "Anthropic,", font=f_big, fill=CREAM)
    d.text((int(SIZE * 0.08), int(SIZE * 0.22) + 320), "Read Aloud", font=f_big, fill=(230, 170, 110))
    d.text((int(SIZE * 0.08), int(SIZE * 0.56)), "Research · News · Claude Blog", font=f_mid, fill=(200, 205, 215))
    d.text((int(SIZE * 0.08), int(SIZE * 0.56) + 200), "Unofficial audio editions, read in full", font=f_small, fill=(170, 175, 185))
    d.text((int(SIZE * 0.08), SIZE - 260), "Not affiliated with Anthropic, PBC", font=f_small, fill=(140, 145, 155))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=85, optimize=True, progressive=True)


def site_icons(cover_path: Path, docs: Path) -> None:
    """Square icons for feed readers / browser tabs: dark tile, big 'A', small waveform in the accent colour."""
    base = 1024
    im = Image.new("RGB", (base, base), (28, 31, 38))
    d = ImageDraw.Draw(im)
    f = _font(BOLD, 700)
    bbox = d.textbbox((0, 0), "A", font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((base - w) / 2 - bbox[0] - 60, (base - h) / 2 - bbox[1] - 90), "A", font=f, fill=CREAM)
    # waveform bars bottom-right
    heights = [90, 160, 240, 170, 110, 200, 130]
    x = base - 60 - len(heights) * 46
    for hh in heights:
        d.rounded_rectangle((x, base - 120 - hh, x + 30, base - 120), radius=15, fill=(230, 170, 110))
        x += 46
    for name, px in (("icon.png", 400), ("favicon.png", 64), ("apple-touch-icon.png", 180)):
        im.resize((px, px), Image.LANCZOS).save(docs / name, "PNG", optimize=True)
