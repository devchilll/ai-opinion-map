"""Parallel crawl: index pages, then articles, then dates. One command.

Two phases, each fully parallel across hosts:
  phase 1  fetch every seed index, extract candidate article links
  phase 2  fetch every candidate article, build Document records

Writes happen once, on the main thread, after each phase.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import trafilatura
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.blogs import article_links, save  # noqa: E402
from collectors.pool import Done, Job, run  # noqa: E402
from schema.models import Audience, DatePrecision, Document, SourceType  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = "crawl_v1"
PER_INDEX_LIMIT = 40


def main(limit: int = PER_INDEX_LIMIT) -> int:
    cfg = yaml.safe_load((ROOT / "data" / "registry" / "sources.yaml").read_text())

    index_jobs = [
        Job(seed["url"], {"person_id": pid, "spec": spec, "seed": seed})
        for pid, spec in cfg["sources"].items()
        for seed in (spec.get("seeds") or [])
    ]
    print(f"phase 1: {len(index_jobs)} index pages across "
          f"{len({urlparse(j.url).netloc for j in index_jobs})} hosts")

    article_jobs: list[Job] = []
    seen_urls: set[str] = set()

    def on_index(d: Done) -> None:
        # A seed marked kind: article IS the document -- no link extraction.
        if d.job.meta["seed"].get("kind") == "article":
            article_jobs.append(Job(d.job.url, d.job.meta))
            return
        if not d.result or not d.result.ok:
            print(f"  ! {d.job.url}: {d.error or d.result.error if d.result else d.error}")
            return
        html = d.result.raw_bytes.decode("utf-8", "replace")
        for url in article_links(html, d.job.url)[:limit]:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            article_jobs.append(Job(url, d.job.meta))

    stats = run(index_jobs, on_result=on_index)
    print(f"phase 1 done: {stats}\n")

    print(f"phase 2: {len(article_jobs)} articles across "
          f"{len({urlparse(j.url).netloc for j in article_jobs})} hosts")
    docs: list[Document] = []

    def on_article(d: Done) -> None:
        if not d.result or not d.result.ok:
            return
        raw = d.result.raw_bytes.decode("utf-8", "replace")
        text = trafilatura.extract(raw) or ""
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if cjk < 400 and len(text.split()) < 120:
            return
        meta = trafilatura.extract_metadata(raw)
        spec, seed = d.job.meta["spec"], d.job.meta["seed"]
        lang = seed.get("language", spec.get("language", "en"))
        docs.append(Document(
            doc_id=d.result.content_hash, person_id=d.job.meta["person_id"],
            source_url=d.job.url, canonical_url=d.result.canonical_url,
            source_type=SourceType(seed.get("source_type", "essay")),
            source_tier=seed.get("tier", spec.get("tier", 1)),
            publisher=(getattr(meta, "sitename", "") or urlparse(d.job.url).netloc),
            title=(getattr(meta, "title", "") or "")[:300],
            authored_by_subject=seed.get("authored_by_subject",
                                         spec.get("authored_by_subject", True)),
            utterance_date=None, publication_date=None,
            date_precision=DatePrecision.QUARTER, language=lang,
            raw_path=d.result.raw_path, raw_content_hash=d.result.content_hash,
            text=text, collector=COLLECTOR, fetched_at=datetime.now(timezone.utc),
            audience=Audience.PUBLIC_POST,
        ))

    stats = run(article_jobs, on_result=on_article)
    print(f"phase 2 done: {stats}")

    inserted = save(docs)      # single writer, main thread, INSERT OR IGNORE
    print(f"\n{len(docs)} documents extracted, {inserted} new rows")
    print("dates are set by `python -m pipeline.feeds` then `python -m pipeline.redate`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
