"""Offline sanity validation of the podcast feed against Apple Podcasts requirements.
Exit 1 on any hard failure. (A second, external validation is done with castfeedvalidator / podba.se.)"""
import sys, re
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd", "atom": "http://www.w3.org/2005/Atom",
      "content": "http://purl.org/rss/1.0/modules/content/", "podcast": "https://podcastindex.org/namespace/1.0"}
path = sys.argv[1]
errs, warns = [], []
root = ET.parse(path).getroot()
ch = root.find("channel")
def req(el, tag, what):
    x = el.find(tag, NS)
    if x is None or not (x.text or x.attrib):
        errs.append(f"{what}: missing <{tag}>")
    return x
for tag in ["title", "link", "description", "language", "itunes:author", "itunes:image", "itunes:category", "itunes:explicit", "atom:link"]:
    req(ch, tag, "channel")
img = ch.find("itunes:image", NS)
if img is not None and not img.get("href", "").startswith("https://"):
    errs.append("channel itunes:image href must be https")
items = ch.findall("item")
if not items:
    errs.append("no items")
guids = set()
for it in items:
    t = it.findtext("title") or "?"
    for tag in ["title", "enclosure", "guid", "pubDate", "description", "itunes:duration"]:
        req(it, tag, f"item {t!r}")
    enc = it.find("enclosure")
    if enc is not None:
        if not enc.get("url", "").startswith("https://"): errs.append(f"{t!r}: enclosure url not https")
        if enc.get("type") != "audio/mpeg": errs.append(f"{t!r}: enclosure type {enc.get('type')}")
        if not (enc.get("length") or "").isdigit() or int(enc.get("length")) < 1000: errs.append(f"{t!r}: bad enclosure length")
    g = it.findtext("guid")
    if g in guids: errs.append(f"duplicate guid {g}")
    guids.add(g)
    try:
        parsedate_to_datetime(it.findtext("pubDate"))
    except Exception:
        errs.append(f"{t!r}: bad pubDate {it.findtext('pubDate')}")
    if len(it.findtext("description") or "") > 4000: warns.append(f"{t!r}: description > 4000 chars")
    if len(t) > 255: warns.append(f"{t!r}: title > 255 chars")
print(f"{path}: {len(items)} items; {len(errs)} errors; {len(warns)} warnings")
for e in errs: print("  ERROR:", e)
for w in warns: print("  warn:", w)
sys.exit(1 if errs else 0)
