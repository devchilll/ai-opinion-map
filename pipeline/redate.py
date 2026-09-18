"""Re-derive dates from the cached raw files. No network access.

This is what the content-addressed raw cache is for: the extraction was wrong,
so fix the extractor and re-run over bytes already on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import connect  # noqa: E402
from pipeline import dates  # noqa: E402

FEED_MAP = Path(__file__).resolve().parent.parent / "data" / "registry" / "feed_dates.json"


def main() -> int:
    import json
    from collectors.base import canonicalize
    feed_dates = json.loads(FEED_MAP.read_text()) if FEED_MAP.exists() else {}
    if feed_dates:
        print(f"using {len(feed_dates)} feed-derived dates")

    with connect() as conn:
        for col, decl in (("date_source", "TEXT DEFAULT ''"), ("date_confidence", "TEXT DEFAULT 'none'"), ("date_note", "TEXT DEFAULT ''")):
            try:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {decl}")
            except Exception:
                pass

        # Never re-derive a date that a collector took from structured feed
        # metadata: scraping the rendered page is strictly worse evidence.
        rows = [dict(r) for r in conn.execute(
            "SELECT doc_id, canonical_url, raw_path, publication_date FROM documents "
            "WHERE COALESCE(date_source,'') != 'rss'")]

        updates = []
        for r in rows:
            raw = Path(r["raw_path"]).read_bytes().decode("utf-8", "replace") if r["raw_path"] else ""
            g = dates.extract(raw, r["canonical_url"],
                              feed_dates.get(canonicalize(r["canonical_url"])))
            updates.append((g.value.isoformat() if g.value else None,
                            g.precision, g.source, g.confidence, g.note, r["doc_id"]))
        conn.executemany(
            "UPDATE documents SET publication_date=?, date_precision=?, date_source=?, "
            "date_confidence=?, date_note=? WHERE doc_id=?", updates)

        rows = [dict(r) for r in conn.execute(
            "SELECT doc_id, canonical_url, publication_date, date_source FROM documents")]
        downgraded = dates.downgrade_clustered(rows)
        if downgraded:
            conn.executemany("UPDATE documents SET date_confidence=? WHERE doc_id=?",
                             [(v, k) for k, v in downgraded.items()])
        print(f"re-dated {len(updates)} documents, downgraded {len(downgraded)} as clustered")

        print("\nconfidence breakdown:")
        for r in conn.execute("SELECT date_confidence c, date_source s, COUNT(*) n FROM documents "
                              "GROUP BY c, s ORDER BY n DESC"):
            print(f"  {r['c']:<8}{r['s']:<10}{r['n']:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
