"""Turn a Post into a speech script: list of (text, pause_after_seconds, kind)."""
from __future__ import annotations
import re
from datetime import datetime
from .config import SOURCES, TTS, PODCAST
from .util import parse_iso

P = TTS["pause"]

ABBREV = [
    (r"\be\.g\.,?", "for example,"), (r"\bi\.e\.,?", "that is,"), (r"\bvs\.?(?=\s|$)", "versus"),
    (r"\betc\.", "et cetera."), (r"\bFig\.\s*(\d+)", r"Figure \1"), (r"\bcf\.", "compare"),
    (r"\bapprox\.", "approximately"), (r"\bNo\.\s*(\d)", r"number \1"), (r"\bDr\.", "Doctor"),
    (r"\bMr\.", "Mister"), (r"\bMs\.", "Miz"), (r"\bMrs\.", "Missus"), (r"\bPh\.?D\.?", "PhD"),
    (r"\bU\.S\.", "US"), (r"\bU\.K\.", "UK"), (r"\bet al\.", "and others"),
]
UNITS = {"MTok": "million tokens", "Mtok": "million tokens", "ms": "milliseconds", "GB": "gigabytes", "TB": "terabytes",
         "MB": "megabytes", "KB": "kilobytes", "GPUs": "G P Us", "GPU": "G P U", "TPUs": "T P Us", "TPU": "T P U", "CPUs": "C P Us",
         "CPU": "C P U", "API": "A P I", "APIs": "A P Is", "SDK": "S D K", "SDKs": "S D Ks", "CLI": "C L I", "UI": "U I",
         "URL": "U R L", "URLs": "U R Ls", "LLM": "L L M", "LLMs": "L L Ms", "AGI": "A G I", "ASL": "A S L", "RL": "R L",
         "RLHF": "R L H F", "SWE": "S W E", "OSS": "O S S", "HTML": "H T M L", "JSON": "Jason", "SQL": "sequel",
         "PDF": "P D F", "PDFs": "P D Fs", "CSV": "C S V", "IDE": "I D E", "IDEs": "I D Es", "MCP": "M C P", "PBC": "P B C",
         "CEO": "C E O", "CTO": "C T O", "COO": "C O O", "PR": "P R", "PRs": "P Rs", "ICML": "I C M L", "NeurIPS": "New-rips",
         "IDs": "I Ds", "ID": "I D", "AWS": "A W S", "GCP": "G C P", "MoE": "mixture of experts", "OCR": "O C R", "QA": "Q A",
         "FAQ": "F A Q", "AI": "A I", "ROI": "R O I", "KPIs": "K P Is", "KPI": "K P I", "B2B": "B to B", "SaaS": "sass",
         "AUC": "A U C", "RAG": "rag", "LOC": "lines of code", "YAML": "yamml", "CSS": "C S S", "HTTP": "H T T P", "HTTPS": "H T T P S",
         "NYC": "N Y C", "SF": "S F", "DC": "D C", "EU": "E U", "UN": "U N", "US": "U S", "UK": "U K", "NLP": "N L P",
         "ML": "M L", "TTS": "T T S", "SOTA": "state of the art", "VLM": "V L M", "VLMs": "V L Ms"}
SYMBOLS = [("→", " to "), ("←", " from "), ("↔", " to and from "), ("×", " times "), ("≈", " approximately "), ("≥", " at least "),
           ("≤", " at most "), ("±", " plus or minus "), ("−", "-"), ("–", " to "), ("—", ", "), ("•", ", "), ("…", "..."),
           (" ", " "), ("​", ""), ("﻿", ""), ("†", ""), ("‡", ""), ("§", "section "), ("©", "copyright "),
           ("™", ""), ("®", ""), ("&", " and "), ("*", ""), ("_", " "), ("`", ""), ("|", ", "), ("~", "about "), ("^", " to the ")]


def _money(m):
    amt, suffix = m.group(1), m.group(2) or ""
    words = {"k": " thousand", "K": " thousand", "M": " million", "B": " billion", "bn": " billion", "m": " million"}.get(suffix, "")
    return f"{amt}{words} dollars"


def normalize(text: str) -> str:
    """Make text friendlier for TTS without changing its meaning."""
    t = re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", text)   # zero-width / soft-hyphen junk
    t = re.sub(r"https?://\S+", lambda m: _url_words(m.group(0)), t)
    for pat, rep in ABBREV:
        t = re.sub(pat, rep, t)
    # money: $5, $5.50, $1.2B, $5/MTok
    t = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)\s?(k|K|M|B|bn|m)?\b", _money, t)
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s?([kKMB])\b(?=[\s\-,.)]|$)", lambda m: m.group(1) + {"k": " thousand", "K": " thousand", "M": " million", "B": " billion"}[m.group(2)], t)
    t = re.sub(r"(\d)x\b", r"\1 x", t)
    t = re.sub(r"\b(\d+)\s*[-–]\s*(\d+)\b", r"\1 to \2", t)           # ranges
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)                           # 1,024 -> 1024 (Kokoro reads fine)
    # units and acronyms (whole-word only)
    def unit(m):
        w = m.group(0)
        return UNITS.get(w, w)
    t = re.sub(r"\b[A-Za-z][A-Za-z0-9]{1,6}\b", unit, t)
    t = re.sub(r"\s*/\s*(million tokens|MTok|month|year|hour|day|week|minute|second|user|seat|token|tokens|image|request|query|call|task|run|episode)\b", r" per \1", t)
    for a, b in SYMBOLS:
        t = t.replace(a, b)
    t = re.sub(r"\[(\d+)\]", r"", t)                                      # [12] citation markers
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    t = re.sub(r"\(\s*\)", "", t)
    return t


def _url_words(u: str) -> str:
    host = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
    return host.replace(".", " dot ")


def _spoken_date(iso: str) -> str:
    d = parse_iso(iso)
    return d.strftime("%B %-d, %Y")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", text)
    return [p.strip() for p in parts if p.strip()]


def chunk(text: str, max_chars: int) -> list[str]:
    """Group sentences into chunks of at most max_chars (long sentences are split on clause boundaries)."""
    out, cur = [], ""
    for s in _sentences(text):
        if len(s) > max_chars:
            # split long sentence on commas/semicolons
            sub, c2 = [], ""
            for piece in re.split(r"(?<=[,;:])\s+", s):
                if len(c2) + len(piece) + 1 > max_chars and c2:
                    sub.append(c2); c2 = piece
                else:
                    c2 = (c2 + " " + piece).strip()
            if c2:
                sub.append(c2)
            for piece in sub:
                if cur:
                    out.append(cur); cur = ""
                out.append(piece)
            continue
        if len(cur) + len(s) + 1 > max_chars and cur:
            out.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def build_script(post) -> list[dict]:
    """Return [{"text": str, "pause": float, "kind": str}] ready for TTS."""
    src = SOURCES[post.source]
    segs: list[dict] = []

    def add(text, pause, kind="body"):
        text = normalize(text)
        if not re.search(r"[A-Za-z0-9]", text):
            return
        added = False
        for c in chunk(text, TTS["max_chunk_chars"]):
            if not re.search(r"[A-Za-z0-9]", c):
                continue
            segs.append({"text": c, "pause": P["sentence"], "kind": kind}); added = True
        if added:
            segs[-1]["pause"] = pause

    # ---- intro
    add(_end(post.title), P["heading_after"], "title")
    if post.subtitle and not _redundant_subtitle(post):
        add(_end(post.subtitle), P["paragraph"], "subtitle")
    by = f" By {_join(post.authors)}." if post.authors else ""
    add(f"From {src['name']}, published {_spoken_date(post.date)}.{by}", P["section"], "meta")

    # ---- body
    n_images = 0
    for b in post.blocks:
        t = b["type"]
        if t == "heading":
            if segs:
                segs[-1]["pause"] = max(segs[-1]["pause"], P["heading_before"])
            add(_end(b["text"].rstrip(":")), P["heading_after"], "heading")
        elif t == "paragraph":
            add(b["text"], P["paragraph"])
        elif t == "list":
            for i, item in enumerate(b["items"], 1):
                prefix = f"{i}. " if b["ordered"] else ""
                add(prefix + item["text"].rstrip(".;,") + ".", P["sentence"] * 2)
            segs[-1]["pause"] = P["paragraph"]
        elif t == "quote":
            add("Quote: " + b["text"].rstrip(".") + ". End quote.", P["paragraph"], "quote")
        elif t == "code":
            lines = [l for l in b["text"].splitlines() if l.strip()]
            if len(lines) <= TTS["max_code_lines_read"]:
                add("Code: " + " ".join(lines) + ".", P["paragraph"], "code")
            else:
                add(f"A code block of {len(lines)} lines appears here; see the original post for the code.", P["paragraph"], "code")
        elif t == "image":
            n_images += 1
            desc = b.get("caption") or ""
            alt = b.get("alt") or ""
            if desc and alt and alt.lower() not in desc.lower() and not alt.lower().startswith(("image", "logo")):
                add(f"Figure {n_images}: {desc.rstrip('.')}. Image description: {alt.rstrip('.')}.", P["paragraph"], "figure")
            elif desc or alt:
                add(f"Figure {n_images}: {(desc or alt).rstrip('.')}.", P["paragraph"], "figure")
            else:
                n_images -= 1  # undescribed image (logo/decoration): nothing to read
        elif t == "table":
            rows = b["rows"]
            cap = f" {b['caption'].rstrip('.')}." if b.get("caption") else ""
            add(f"Table with {len(rows)} rows.{cap}", P["sentence"] * 2, "table")
            header = rows[0] if rows else []
            for r in rows[:40]:
                if r is header:
                    add("Header: " + "; ".join(c for c in r if c) + ".", P["sentence"] * 2, "table")
                else:
                    cells = [f"{header[i]}: {c}" if i < len(header) and header[i] and len(rows) > 1 else c for i, c in enumerate(r) if c]
                    add("; ".join(cells) + ".", P["sentence"] * 2, "table")
            if len(rows) > 40:
                add(f"The table continues for {len(rows) - 40} more rows; see the original post.", P["paragraph"], "table")
            segs[-1]["pause"] = P["paragraph"]
        elif t == "footnotes":
            segs[-1]["pause"] = P["section"]
            add("Footnotes.", P["heading_after"], "heading")
            for it in b["items"]:
                add(f"Footnote {it['n']}: {it['text']}", P["paragraph"])

    # ---- outro
    segs[-1]["pause"] = P["section"]
    add(f"That was {post.title.rstrip('.')}, from {src['name']}, published {_spoken_date(post.date)}. "
        f"Read the original at {_url_words(post.url)}. This unofficial audio edition was generated automatically "
        f"for the podcast {PODCAST['title']}.", P["paragraph"], "outro")
    return segs


def _end(text: str) -> str:
    """Ensure a chunk ends with terminal punctuation (adds a period when there is none)."""
    t = text.strip()
    return t if re.search(r"[.!?…]['\")”’]*$", t) else t + "."


def _redundant_subtitle(post) -> bool:
    """anthropic.com's og:description is often just the first body paragraph(s); don't read it twice."""
    sub = re.sub(r"\s+", " ", post.subtitle).strip().lower()
    if not sub or sub.rstrip(".") == post.title.strip().lower().rstrip("."):
        return True
    body = " ".join(b["text"] for b in post.blocks[:3] if b["type"] == "paragraph")
    body = re.sub(r"\s+", " ", body).lower()
    probe = sub[:80]
    return bool(probe) and probe in body


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def transcript_text(segs: list[dict]) -> str:
    out, para = [], []
    for s in segs:
        para.append(s["text"])
        if s["pause"] >= P["paragraph"]:
            out.append(" ".join(para)); para = []
    if para:
        out.append(" ".join(para))
    return "\n\n".join(out)
