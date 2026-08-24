"""Episode artwork (3000×3000 JPEG built from the post's hero image) and the show cover.

Anthropic and Claude hero illustrations sit on a flat background colour. The generator
detects that colour, keys the illustration out of it, and rebuilds the canvas as a rich
vertical gradient of the same hue with a radial glow behind the floating art, a soft
drop shadow, and film grain — so every episode keeps the post's own art and colour but
reads loud and glossy at thumbnail size. Photographic heroes get a full-bleed crop with
a tinted gradient scrim; posts with no usable hero fall back to a per-source palette.
"""
from __future__ import annotations
import colorsys
import io
import zlib
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from .config import FONTS, SOURCES, PODCAST
from .util import http_get, log

SIZE = 3000
MARGIN = int(SIZE * 0.07)
PALETTE = {"research": (31, 64, 59), "news": (122, 52, 35), "claude-blog": (45, 52, 96)}  # fallback bg per source
CREAM = (244, 239, 230)
INK = (28, 26, 22)
ACCENT = (204, 120, 92)         # Anthropic "book cloth" rust
ACCENT_LIGHT = (224, 152, 122)  # same accent lifted for dark backgrounds
DISPLAY = FONTS / "ArchivoBlack-Regular.ttf"
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


def _adjust(c, *, sat: float = 1.0, val: float = 1.0) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
    r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s * sat), min(1.0, v * val))
    return (int(r * 255), int(g * 255), int(b * 255))


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


def _tracked_len(d, text, font, tracking=0):
    return sum(d.textlength(ch, font=font) + tracking for ch in text)


def _waveform(d, x, y_base, fill, scale=1.0):
    """Small waveform mark (matches the site icon); returns its width."""
    heights, bar, gap = (58, 104, 156, 110, 72, 130, 84), 22, 14
    for h in heights:
        hh = int(h * scale)
        d.rounded_rectangle((x, y_base - hh, x + int(bar * scale), y_base), radius=int(11 * scale), fill=fill)
        x += int((bar + gap) * scale)
    return len(heights) * int((bar + gap) * scale)


def _gradient_canvas(base, *, glow_center=None, glow_color=None) -> Image.Image:
    """Saturated vertical gradient of `base` with an optional radial glow and a vignette."""
    lo = 188  # build small, upscale — the gradients are smooth
    top = np.array(_adjust(base, sat=1.22, val=1.16), dtype=np.float32)
    bot = np.array(_adjust(base, sat=1.30, val=0.68), dtype=np.float32)
    t = np.linspace(0, 1, lo, dtype=np.float32)[:, None, None] ** 1.25
    arr = top[None, None, :] * (1 - t) + bot[None, None, :] * t
    yy, xx = np.mgrid[0:lo, 0:lo].astype(np.float32) / (lo - 1)
    if glow_center is not None:
        gc = np.array(glow_color if glow_color is not None else _adjust(base, sat=0.85, val=1.45), dtype=np.float32)
        cx, cy = glow_center[0] / SIZE, glow_center[1] / SIZE
        dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
        glow = np.exp(-dist2 / (2 * 0.30 ** 2))[:, :, None] * 0.35
        arr = arr * (1 - glow) + gc[None, None, :] * glow
    # vignette
    edge2 = (xx - 0.5) ** 2 + (yy - 0.5) ** 2
    vig = np.clip((np.sqrt(edge2) - 0.52) / 0.35, 0, 1)[:, :, None] * 0.16
    arr *= 1 - vig
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return im.resize((SIZE, SIZE), Image.BICUBIC)


def _key_out(hero: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Hero as RGBA with its flat background colour keyed to transparent (soft edges)."""
    a = np.asarray(hero, dtype=np.float32)
    dist = np.sqrt(((a - np.array(bg, dtype=np.float32)) ** 2).sum(axis=2))
    alpha = np.clip((dist - 16) / (64 - 16), 0, 1) * 255
    out = np.dstack([a, alpha]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _trim_sparse(art: Image.Image) -> Image.Image:
    """Crop keyed art to its dense content band, dropping stray caption/label rows
    (thin text lines key out to very low per-row alpha density)."""
    alpha = np.asarray(art.split()[3], dtype=np.float32)
    rows = alpha.sum(axis=1)
    filled = rows > rows.max() * 0.02
    # contiguous bands of content, merged across small gaps
    idx = np.where(filled)[0]
    if len(idx) == 0:
        return art
    breaks = np.where(np.diff(idx) > 1)[0]
    bands = np.split(idx, breaks + 1)
    groups, cur = [], [bands[0]]
    for b in bands[1:]:
        if b[0] - cur[-1][-1] < art.height * 0.06:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)
    main = max(groups, key=lambda g: sum(rows[b].sum() for b in g))
    top, bot = int(main[0][0]), int(main[-1][-1])
    pad = int(art.height * 0.02)
    return art.crop((0, max(0, top - pad), art.width, min(art.height, bot + pad)))


def _paste_with_shadow(canvas: Image.Image, art: Image.Image, x: int, y: int):
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sil = Image.new("RGBA", art.size, (0, 0, 0, 110))
    sil.putalpha(art.split()[3].point(lambda v: v * 110 // 255))
    shadow.paste(sil, (x + 10, y + 45), sil)
    shadow = shadow.filter(ImageFilter.GaussianBlur(45))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(art, (x, y))


def _grain(canvas: Image.Image, seed: int, amount: float = 3.2) -> Image.Image:
    """Fine monochrome film grain; also breaks up JPEG banding on the gradients."""
    rng = np.random.default_rng(seed)
    a = np.asarray(canvas, dtype=np.float32)
    noise = rng.standard_normal(a.shape[:2], dtype=np.float32)[:, :, None] * amount
    return Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8), "RGB")


def _fit_title(d, title, max_w, max_h):
    """Largest title size whose wrapped lines fit the box; prefers no truncation."""
    best = None
    for size in range(232, 108, -12):
        f = _font(DISPLAY, size)
        lines = _wrap(d, title, f, max_w, 4)
        line_h = int(size * 1.16)
        if len(lines) * line_h > max_h:
            continue
        truncated = lines and lines[-1].endswith("…")
        if not truncated:
            return f, lines, line_h
        if best is None:
            best = (f, lines, line_h)
    if best:
        return best
    f = _font(DISPLAY, 108)
    return f, _wrap(d, title, f, max_w, 4), int(108 * 1.16)


def _text_block(canvas, post, bg, top, bottom, episode: int | None = None):
    """Chips + title + footer, coloured for contrast against bg, centred in [top, bottom]."""
    d = ImageDraw.Draw(canvas)
    dark_bg = _luma(bg) < 140
    ink = CREAM if dark_bg else INK
    muted = _blend(ink, bg, 0.28)
    accent = ACCENT_LIGHT if dark_bg else (ACCENT if _luma(bg) > 200 else ink)
    max_w = SIZE - 2 * MARGIN

    f_chip = _font(BOLD, 58)
    chip_h, chip_gap = 118, 84
    footer_h = 250
    avail = (bottom - footer_h) - top
    f_title, lines, line_h = _fit_title(d, post.title, max_w, avail - chip_h - chip_gap)
    block_h = chip_h + chip_gap + len(lines) * line_h
    y = top + max(0, (avail - block_h) // 2)

    # source chip: solid accent pill, ink text; date + episode number beside it
    label = SOURCES[post.source]["name"].upper()
    pad = 44
    w = _tracked_len(d, label, f_chip, 6) + 2 * pad
    d.rounded_rectangle((MARGIN, y, MARGIN + w, y + chip_h), radius=chip_h // 2, fill=ACCENT)
    _tracked_text(d, (MARGIN + pad, y + (chip_h - 58) // 2 - 6), label, f_chip, INK, tracking=6)
    meta = _human_date(post.date).upper() + (f"   ·   EP {episode}" if episode else "")
    _tracked_text(d, (MARGIN + w + 52, y + (chip_h - 58) // 2 - 6), meta, f_chip, muted, tracking=6)
    y += chip_h + chip_gap
    for ln in lines:
        d.text((MARGIN, y), ln, font=f_title, fill=ink)
        y += line_h

    f_foot = _font(REG, 56)
    foot_y = SIZE - 150
    d.text((MARGIN, foot_y - 56), f"{PODCAST['title']}  ·  unofficial audio edition", font=f_foot, fill=muted)
    _waveform(d, SIZE - MARGIN - 260, foot_y, accent)


def episode_art(post, out_path: Path, episode: int | None = None) -> bytes:
    hero = _fetch_image(post.hero) if post.hero else None
    flat = _edge_color(hero) if hero is not None else None

    if hero is not None and flat is not None:
        # key the illustration out of its flat background and float it on a glossy
        # gradient of the same colour, glow behind it, soft shadow underneath
        art = _key_out(hero, flat)
        bbox = art.getbbox()
        if bbox:
            art = art.crop(bbox)
        art = _trim_sparse(art)
        art.thumbnail((int(SIZE * 0.92), int(SIZE * 0.56)), Image.LANCZOS)
        cx, cy = SIZE // 2, int(SIZE * 0.28)
        base = _gradient_canvas(flat, glow_center=(cx, cy))
        canvas = base.convert("RGBA")
        x, y = cx - art.width // 2, max(110, cy - art.height // 2)
        _paste_with_shadow(canvas, art, x, y)
        canvas = canvas.convert("RGB")
        mid = _blend(_adjust(flat, sat=1.25, val=1.05), _adjust(flat, sat=1.3, val=0.72), 0.5)
        _text_block(canvas, post, mid, y + art.height + int(SIZE * 0.03), SIZE, episode)
    elif hero is not None:
        # photographic hero: full-bleed crop, tinted gradient scrim for the text
        canvas = ImageOps.fit(hero, (SIZE, SIZE), Image.LANCZOS)
        avg = tuple(int(c) for c in np.asarray(canvas.resize((8, 8))).reshape(-1, 3).mean(axis=0))
        panel = _blend(_adjust(avg, sat=1.2), (12, 12, 15), 0.80)
        panel_top = int(SIZE * 0.42)
        arr = np.asarray(canvas, dtype=np.float32)
        t = np.clip((np.arange(SIZE, dtype=np.float32) - panel_top) / (SIZE * 0.16), 0, 1)[:, None, None]
        arr = arr * (1 - t) + np.array(panel, dtype=np.float32)[None, None, :] * t
        canvas = Image.fromarray(arr.astype(np.uint8), "RGB")
        _text_block(canvas, post, panel, panel_top + int(SIZE * 0.10), SIZE, episode)
    else:
        base = PALETTE.get(post.source, (40, 40, 40))
        canvas = _gradient_canvas(base, glow_center=(SIZE // 2, int(SIZE * 0.22)))
        d = ImageDraw.Draw(canvas)
        _waveform(d, MARGIN, int(SIZE * 0.30), _blend(base, CREAM, 0.22), scale=6.0)
        mid = _blend(_adjust(base, sat=1.25, val=1.05), _adjust(base, sat=1.3, val=0.72), 0.5)
        _text_block(canvas, post, mid, int(SIZE * 0.38), SIZE, episode)

    canvas = _grain(canvas, zlib.crc32(post.slug.encode()))
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
    base = (36, 40, 52)
    canvas = _gradient_canvas(base, glow_center=(int(SIZE * 0.72), int(SIZE * 0.20)),
                              glow_color=_blend(base, ACCENT, 0.45))
    d = ImageDraw.Draw(canvas)
    f_big = _font(DISPLAY, 296)
    f_mid = _font(BOLD, 120)
    f_small = _font(REG, 78)
    x = int(SIZE * 0.08)
    _waveform(d, x, int(SIZE * 0.245), ACCENT_LIGHT, scale=2.6)
    d.text((x, int(SIZE * 0.30)), "Anthropic,", font=f_big, fill=CREAM)
    d.text((x, int(SIZE * 0.30) + 340), "Read Aloud", font=f_big, fill=ACCENT_LIGHT)
    d.text((x, int(SIZE * 0.62)), "Research · News · Claude Blog", font=f_mid, fill=(206, 211, 224))
    d.text((x, int(SIZE * 0.62) + 190), "Unofficial audio editions, read in full", font=f_small, fill=(172, 178, 192))
    d.text((x, SIZE - 250), "Not affiliated with Anthropic, PBC", font=f_small, fill=(140, 146, 160))
    canvas = _grain(canvas, zlib.crc32(b"show-cover"))
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
