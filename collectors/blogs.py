"""Blogs collector: index page -> article links -> Document records.

Converts one external format (HTML) into the canonical schema. It does not
score, classify, or interpret anything.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import trafilatura
import yaml
from dateutil import parser as dateparser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import Fetcher, canonicalize  # noqa: E402
from pipeline.db import connect  # noqa: E402
from schema.models import Audience, DatePrecision, Document, SourceType, to_row  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = "blogs_v1"

# Static assets and framework internals are not articles. Left unfiltered they
# consume the whole per-page link budget on modern sites -- Suleyman's Next.js
# site yielded zero documents because fonts and CSS filled every slot.
_SKIP = re.compile(
    r"(mailto:|tel:|javascript:|"
    r"\.(pdf|jpe?g|png|gif|svg|webp|ico|zip|gz|mp[34]|woff2?|ttf|eot|css|js|json|xml|rss)(\?|$)|"
    r"/_next/|/static/|/assets/|/wp-content/|/wp-json/|/cdn-cgi/|"
    r"/tag/|/category/|/author/|/page/\d|"
    r"twitter\.com|x\.com|linkedin\.com|facebook\.com|youtube\.com|github\.com|"
    r"instagram\.com|t\.co/)",
    re.I,
)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def article_links(html: str, base_url: str, *, same_host_only: bool = True) -> list[str]:
    base_host = urlparse(base_url).netloc
    out, seen = [], set()
    for href in _HREF.findall(html):
        if href.startswith("#") or _SKIP.search(href):
            continue
        url = canonicalize(urljoin(base_url, href))
        if same_host_only and urlparse(url).netloc != base_host:
            continue
        if url.rstrip("/") == base_url.rstrip("/") or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def parse_date(meta, text: str) -> tuple[datetime | None, DatePrecision]:
    if meta and getattr(meta, "date", None):
        try:
            return dateparser.parse(meta.date), DatePrecision.DAY
        except (ValueError, TypeError):
            pass
    m = re.search(r"\b(20[0-2]\d)\b", text[:400])
    if m:
        return datetime(int(m.group(1)), 7, 1), DatePrecision.QUARTER
    return None, DatePrecision.QUARTER


def collect(person_id: str, spec: dict, fetcher: Fetcher, *, limit: int) -> list[Document]:
    docs: list[Document] = []
    for seed in spec["seeds"]:
        if seed.get("status") == "dead":
            continue
        index = fetcher.fetch(seed["url"])
        if not index.ok:
            print(f"  ! index unreachable: {seed['url']} ({index.error})")
            continue
        html = index.raw_bytes.decode("utf-8", "replace")
        links = article_links(html, seed["url"])[:limit]
        print(f"  {seed['url']} -> {len(links)} candidate articles")

        authored = seed.get("authored_by_subject", spec.get("authored_by_subject", True))
        for url in links:
            res = fetcher.fetch(url)
            if not res.ok:
                continue
            raw = res.raw_bytes.decode("utf-8", "replace")
            text = trafilatura.extract(raw) or ""
            if len(text.split()) < 120:          # nav pages, stubs
                continue
            meta = trafilatura.extract_metadata(raw)
            dt, precision = parse_date(meta, text)
            docs.append(Document(
                doc_id=res.content_hash,
                person_id=person_id,
                source_url=url,
                canonical_url=res.canonical_url,
                source_type=SourceType.ESSAY,
                source_tier=spec.get("tier", 1),
                publisher=(getattr(meta, "sitename", "") or urlparse(url).netloc),
                title=(getattr(meta, "title", "") or "")[:300],
                authored_by_subject=authored,
                utterance_date=None,
                publication_date=dt.date() if dt else None,
                date_precision=precision,
                language="en",
                raw_path=res.raw_path,
                raw_content_hash=res.content_hash,
                text=text,
                collector=COLLECTOR,
                fetched_at=datetime.now(timezone.utc),
                audience=Audience.PUBLIC_POST,
            ))
    return docs


def save(docs: list[Document]) -> int:
    """Single writer. INSERT OR IGNORE on a unique canonical_url makes a re-run
    idempotent, so two crawls cannot duplicate or half-overwrite a document."""
    if not docs:
        return 0
    cols = list(to_row(docs[0]).keys())
    sql = (f"INSERT OR IGNORE INTO documents ({','.join(cols)}) "
           f"VALUES ({','.join('?' for _ in cols)})")
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.executemany(sql, [tuple(to_row(d)[c] for c in cols) for d in docs])
        after = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return after - before


def main(limit: int = 25) -> int:
    cfg = yaml.safe_load((ROOT / "data" / "registry" / "sources.yaml").read_text())
    fetcher = Fetcher()
    all_docs: list[Document] = []
    try:
        for person_id, spec in cfg["sources"].items():
            print(f"\n{person_id}")
            all_docs += collect(person_id, spec, fetcher, limit=limit)
    finally:
        fetcher.close()
    inserted = save(all_docs)
    print(f"\n{len(all_docs)} documents extracted, {inserted} new rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
