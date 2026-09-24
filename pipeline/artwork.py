"""Episode artwork (3000×3000 JPEG built from the post's hero image) and the show cover.

Art-forward and quiet: the post's illustration fills the square on its own flat
background colour, with only a small source label and show name along the bottom — the
episode title lives in the podcast app. Anthropic and Claude hero illustrations sit on a
flat colour; the generator detects it, keys the illustration out, and re-centres it on a
square canvas of that exact colour. Sparse line drawings are zoomed in until they fill the
frame edge to edge (never cropped), so minimal art doesn't float small in empty colour. Photographic heroes are shown whole as a
rounded tile on a deep tint of their own colour; posts with no hero get the waveform mark
on a per-source colour.
"""
from __future__ import annotations
import io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .config import FONTS, SOURCES, PODCAST
from .util import http_get, log

SIZE = 3000
MARGIN = 200
IVORY = (240, 238, 230)
SLATE = (20, 20, 19)
CLAY = (217, 119, 87)
PALETTE = {"research": (188, 209, 202), "news": (203, 202, 219), "claude-blog": CLAY}  # no-hero bg per source
LABEL = FONTS / "Inter-SemiBold.ttf"
MEDIUM = FONTS / "Inter-Medium.ttf"
SERIF = FONTS / "SourceSerif4-SemiBold.ttf"

ART_CENTER_Y = 0.44     # vertical centre of the illustration, as a fraction of SIZE
ART_BOX = (0.78, 0.64)  # fit box for dense art (fractions of SIZE)
LABEL_Y = SIZE - 250    # baseline row for the source + show labels
FADE = (0.80, 0.86)     # art that reaches this band fades out before the labels
ART_MAX = (0.92, 0.74)  # zoomed art never grows past this (fractions of SIZE) — no cropping
ZOOM_MAX = 1.35         # extra scale for the sparsest line art
DENSE, SPARSE = 0.50, 0.18  # ink coverage at which zoom is 1.0 / ZOOM_MAX


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


def _ink(bg) -> tuple[int, int, int]:
    return SLATE if _luma(bg) > 150 else IVORY


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


def _place_art(canvas: Image.Image, art: Image.Image):
    """Scale keyed art into the frame — zooming sparse line drawings up until they fill it,
    never cropping — and composite it, fading anything that would reach the label row."""
    coverage = float(np.asarray(art.split()[3], dtype=np.float32).mean() / 255)
    zoom = 1 + (ZOOM_MAX - 1) * float(np.clip((DENSE - coverage) / (DENSE - SPARSE), 0, 1))
    r = min(ART_BOX[0] * SIZE / art.width, ART_BOX[1] * SIZE / art.height) * zoom
    r = min(r, ART_MAX[0] * SIZE / art.width, ART_MAX[1] * SIZE / art.height)
    w, h = max(1, round(art.width * r)), max(1, round(art.height * r))
    x, y = (SIZE - w) // 2, max(MARGIN // 2, round(ART_CENTER_Y * SIZE - h / 2))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    art = art.resize((w, h), Image.LANCZOS)
    layer.paste(art, (x, y), art)
    fade = np.clip((FADE[1] * SIZE - np.arange(SIZE, dtype=np.float32)) / ((FADE[1] - FADE[0]) * SIZE), 0, 1)
    alpha = np.asarray(layer.split()[3], dtype=np.float32) * fade[:, None]
    layer.putalpha(Image.fromarray(alpha.astype(np.uint8), "L"))
    canvas.alpha_composite(layer)


def _labels(canvas: Image.Image, post, bg, ink):
    d = ImageDraw.Draw(canvas)
    _tracked_text(d, (MARGIN, LABEL_Y), SOURCES[post.source]["name"].upper(), _font(LABEL, 64), ink, tracking=8)
    show = PODCAST["title"].upper()
    f = _font(MEDIUM, 64)
    _tracked_text(d, (SIZE - MARGIN - _tracked_len(d, show, f, 8), LABEL_Y), show, f, _blend(ink, bg, 0.3), tracking=8)


def _rounded_tile(img: Image.Image, size, radius):
    tile = ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.45))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return tile, mask


def _save_jpeg(canvas: Image.Image, out_path: Path, thumb: bool) -> bytes:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    quality = 86
    while True:
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() < 900_000 or quality <= 55:
            break
        quality -= 7
    data = buf.getvalue()
    out_path.write_bytes(data)
    if thumb:  # 600px companion thumbnail for the site's episode cards
        canvas.resize((600, 600), Image.LANCZOS).save(out_path.with_suffix(".600.jpg"), "JPEG",
                                                      quality=82, optimize=True, progressive=True)
    return data


def episode_art(post, out_path: Path) -> bytes:
    hero = _fetch_image(post.hero) if post.hero else None
    flat = _edge_color(hero) if hero is not None else None

    if hero is not None and flat is not None:
        bg = flat
        canvas = Image.new("RGBA", (SIZE, SIZE), bg + (255,))
        art = _key_out(hero, flat)
        bbox = art.getbbox()
        if bbox:
            art = _trim_sparse(art.crop(bbox))
            _place_art(canvas, art)
    elif hero is not None:
        # photographic hero: shown whole (baked-in text survives) on a deep tint of its colour
        avg = tuple(int(c) for c in np.asarray(hero.resize((8, 8))).reshape(-1, 3).mean(axis=0))
        bg = _blend(avg, SLATE, 0.8)
        canvas = Image.new("RGBA", (SIZE, SIZE), bg + (255,))
        tw = SIZE - 2 * MARGIN
        th = min(round(tw * hero.height / hero.width), int(SIZE * 0.62))
        tile, mask = _rounded_tile(hero, (tw, th), 36)
        canvas.paste(tile, (MARGIN, int(ART_CENTER_Y * SIZE) - th // 2), mask)
    else:
        bg = PALETTE.get(post.source, CLAY)
        canvas = Image.new("RGBA", (SIZE, SIZE), bg + (255,))
        d = ImageDraw.Draw(canvas)
        scale = 6.2
        _waveform(d, (SIZE - 7 * int(36 * scale)) // 2, int(ART_CENTER_Y * SIZE + 80 * scale),
                  _blend(_ink(bg), bg, 0.2), scale=scale)

    _labels(canvas, post, bg, _ink(bg))
    return _save_jpeg(canvas.convert("RGB"), out_path, thumb=True)


def show_cover(out_path: Path) -> None:
    """Show cover in the same language as the episodes: flat clay, the waveform mark as
    the illustration, the show name set in the serif, a quiet label row."""
    bg, ink = CLAY, SLATE
    canvas = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(canvas)
    scale = 5.4
    _waveform(d, (SIZE - 7 * int(36 * scale)) // 2, int(SIZE * 0.40), IVORY, scale=scale)
    f = _font(SERIF, 300)
    for i, line in enumerate(("Anthropic,", "Read Aloud")):
        w = d.textlength(line, font=f)
        d.text(((SIZE - w) / 2, SIZE * 0.47 + i * 340), line, font=f, fill=ink)
    muted = _blend(ink, bg, 0.3)
    f_lab = _font(MEDIUM, 64)
    for text, x_align in (("RESEARCH · NEWS · CLAUDE BLOG", "left"), ("UNOFFICIAL AUDIO EDITIONS", "right")):
        w = _tracked_len(d, text, f_lab, 8)
        x = MARGIN if x_align == "left" else SIZE - MARGIN - w
        _tracked_text(d, (x, LABEL_Y), text, f_lab, muted, tracking=8)
    _save_jpeg(canvas, out_path, thumb=False)


def site_icons(cover_path: Path, docs: Path) -> None:
    """Square icons for feed readers / browser tabs: the ivory waveform mark on clay."""
    base = 1024
    im = Image.new("RGB", (base, base), CLAY)
    d = ImageDraw.Draw(im)
    scale = 3.2
    _waveform(d, (base - 7 * int(36 * scale)) // 2, base // 2 + int(80 * scale), IVORY, scale=scale)
    for name, px in (("icon.png", 400), ("favicon.png", 64), ("apple-touch-icon.png", 180)):
        im.resize((px, px), Image.LANCZOS).save(docs / name, "PNG", optimize=True)
