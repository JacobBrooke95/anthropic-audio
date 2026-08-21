"""Find candidate post URLs: sitemaps (authoritative) + listing pages (fast path)."""
from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .config import SOURCES
from .util import http_get, log


def _clean(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"


def _is_post(url: str, prefix: str) -> bool:
    if not url.startswith(prefix):
        return False
    rest = url[len(prefix):]
    return bool(rest) and "/" not in rest and "?" not in rest and "#" not in rest and not rest.startswith("page")


def discover() -> dict[str, dict]:
    """Return {url: {"source": key, "lastmod": iso|None, "via": "sitemap"|"listing"}}."""
    found: dict[str, dict] = {}
    sitemap_cache: dict[str, str] = {}
    for key, src in SOURCES.items():
        # --- sitemap
        try:
            xml = sitemap_cache.get(src["sitemap"]) or http_get(src["sitemap"])
            sitemap_cache[src["sitemap"]] = xml
            for m in re.finditer(r"<url>(.*?)</url>", xml, re.S):
                block = m.group(1)
                loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
                if not loc:
                    continue
                url = _clean(loc.group(1))
                if _is_post(url, src["prefix"]):
                    lm = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
                    found.setdefault(url, {"source": key, "lastmod": lm.group(1) if lm else None, "via": "sitemap"})
        except Exception as e:  # sitemap outage must not stop listing crawl
            log.warning("sitemap %s failed: %s", src["sitemap"], e)
        # --- listing page
        try:
            html = http_get(src["listing"])
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                url = _clean(urljoin(src["listing"], a["href"]))
                if _is_post(url, src["prefix"]):
                    found.setdefault(url, {"source": key, "lastmod": None, "via": "listing"})
        except Exception as e:
            log.warning("listing %s failed: %s", src["listing"], e)
    log.info("discover: %d candidate urls", len(found))
    return found
