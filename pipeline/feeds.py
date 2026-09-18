"""Feed-derived dates: the most reliable date source a site can offer.

Some sites never print a date in the page body -- Altman's Posthaven blog is one
-- but publish exact timestamps in their Atom/RSS feed. A feed entry's
<published> is authored by the publishing system rather than by a template, so
it is better evidence than anything scraped from rendered HTML.

Feeds are treated as a 'structured' family source, so a feed date agreeing with
a visible dateline counts as genuine corroboration.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import feedparser
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import Fetcher, canonicalize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FEED_MAP = ROOT / "data" / "registry" / "feed_dates.json"

_FEED_LINK = re.compile(
    r'<link[^>]+type=["\']application/(?:atom|rss)\+xml["\'][^>]*>', re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_COMMON = ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml", "/posts.atom")


def discover(html: str, base_url: str) -> list[str]:
    from urllib.parse import urljoin
    out = []
    for tag in _FEED_LINK.findall(html):
        m = _HREF.search(tag)
        if m:
            out.append(urljoin(base_url, m.group(1)))
    return out


def harvest(fetcher: Fetcher, index_urls: list[str]) -> dict[str, str]:
    """{canonical article url: ISO date} from every feed we can find."""
    mapping: dict[str, str] = {}
    tried: set[str] = set()

    for index_url in index_urls:
        res = fetcher.fetch(index_url)
        candidates: list[str] = []
        if res.ok:
            candidates += discover(res.raw_bytes.decode("utf-8", "replace"), index_url)
        root = "/".join(index_url.split("/")[:3])
        candidates += [root + p for p in _COMMON]

        for feed_url in candidates:
            cu = canonicalize(feed_url)
            if cu in tried:
                continue
            tried.add(cu)
            fr = fetcher.fetch(feed_url)
            if not fr.ok:
                continue
            parsed = feedparser.parse(fr.raw_bytes)
            if not parsed.entries:
                continue
            got = 0
            for e in parsed.entries:
                link = e.get("link")
                st = e.get("published_parsed") or e.get("updated_parsed")
                if link and st:
                    mapping[canonicalize(link)] = date(st.tm_year, st.tm_mon, st.tm_mday).isoformat()
                    got += 1
            if got:
                print(f"  {feed_url} -> {got} dated entries")
    return mapping


def main() -> int:
    import json
    cfg = yaml.safe_load((ROOT / "data" / "registry" / "sources.yaml").read_text())
    index_urls = [s["url"] for spec in cfg["sources"].values() for s in (spec.get("seeds") or [])]
    fetcher = Fetcher()
    try:
        mapping = harvest(fetcher, index_urls)
    finally:
        fetcher.close()
    FEED_MAP.write_text(json.dumps(mapping, indent=1, sort_keys=True))
    print(f"\n{len(mapping)} article dates harvested from feeds -> {FEED_MAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
