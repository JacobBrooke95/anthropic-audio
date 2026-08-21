"""Episode artwork (3000×3000 JPEG built from the post's hero image) and the show cover."""
from __future__ import annotations
import io, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from .config import FONTS, SOURCES, PODCAST
from .util import http_get, log

SIZE = 3000
PALETTE = {"research": (31, 64, 59), "news": (122, 52, 35), "claude-blog": (45, 52, 96)}  # fallback bg per source
CREAM = (244, 239, 230)
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


def episode_art(post, out_path: Path) -> bytes:
    src = SOURCES[post.source]
    hero = _fetch_image(post.hero) if post.hero else None
    canvas = Image.new("RGB", (SIZE, SIZE), PALETTE.get(post.source, (40, 40, 40)))
    if hero is not None:
        bg = ImageOps.fit(hero, (SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(70))
        bg = Image.blend(bg, Image.new("RGB", (SIZE, SIZE), (10, 10, 12)), 0.55)
        canvas.paste(bg, (0, 0))
        # foreground: hero fit into the upper area
        box_w, box_h = int(SIZE * 0.86), int(SIZE * 0.50)
        fg = hero.copy(); fg.thumbnail((box_w, box_h), Image.LANCZOS)
        x = (SIZE - fg.width) // 2; y = int(SIZE * 0.09)
        shadow = Image.new("RGB", (fg.width + 40, fg.height + 40), (0, 0, 0))
        canvas.paste(Image.blend(canvas.crop((x - 20, y - 20, x - 20 + shadow.width, y - 20 + shadow.height)), shadow, 0.5), (x - 20, y - 20))
        canvas.paste(fg, (x, y))
        text_top = y + fg.height + int(SIZE * 0.06)
    else:
        text_top = int(SIZE * 0.20)
    d = ImageDraw.Draw(canvas)
    # eyebrow
    eyebrow = f"{src['name'].upper()}  ·  {post.date[:10]}"
    f_eye = _font(BOLD, 70)
    d.text((int(SIZE * 0.07), text_top), eyebrow, font=f_eye, fill=(230, 200, 150))
    # title
    f_title = _font(BOLD, 150)
    lines = _wrap(d, post.title, f_title, int(SIZE * 0.86), 4)
    y = text_top + 130
    for ln in lines:
        d.text((int(SIZE * 0.07), y), ln, font=f_title, fill=CREAM)
        y += 175
    # footer
    f_foot = _font(REG, 60)
    foot = f"{PODCAST['title']}  —  unofficial audio edition"
    d.text((int(SIZE * 0.07), SIZE - 170), foot, font=f_foot, fill=(200, 200, 200))
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
