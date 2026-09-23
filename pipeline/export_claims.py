"""Export the receipts: every claim, with its quote, scores and source link.

This is what the person panel renders. The quote is the substance of the UI,
not a footnote -- a coordinate with no visible source is an accusation.
Quotes are already capped at 50 words / 120 CJK characters by the validator,
which keeps the display inside fair-use territory for tier-3 sources.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "out" / "claims.json"


def main() -> int:
    with connect() as conn:
        rows = conn.execute("""
            SELECT c.claim_id, c.person_id, c.date, c.date_precision, c.supporting_text,
                   c.normalized_claim, c.topics, c.axis_scores, c.hedged, c.timeline_years,
                   c.human_reviewed, c.extractor_model,
                   d.canonical_url, d.title, d.publisher, d.source_type, d.source_tier,
                   d.language, d.date_confidence
            FROM claims c JOIN documents d ON d.doc_id = c.doc_id
            WHERE d.date_confidence IN ('high','medium')
            ORDER BY c.person_id, c.date DESC
        """).fetchall()

    by_person: dict[str, list[dict]] = {}
    for r in rows:
        by_person.setdefault(r["person_id"], []).append({
            "id": r["claim_id"],
            "date": str(r["date"])[:10],
            "precision": r["date_precision"],
            "quote": r["supporting_text"],
            "claim": r["normalized_claim"],
            "topics": json.loads(r["topics"] or "[]"),
            "scores": json.loads(r["axis_scores"] or "[]"),
            "hedged": bool(r["hedged"]),
            "timeline_years": r["timeline_years"],
            "reviewed": bool(r["human_reviewed"]),
            "extractor": r["extractor_model"],
            "source": {
                "url": r["canonical_url"], "title": r["title"], "publisher": r["publisher"],
                "type": r["source_type"], "tier": r["source_tier"], "language": r["language"],
            },
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(by_person, ensure_ascii=False, separators=(",", ":")))
    total = sum(len(v) for v in by_person.values())
    print(f"{total} claims for {len(by_person)} people -> {OUT} ({OUT.stat().st_size // 1024} KB)")
    for pid, cl in sorted(by_person.items(), key=lambda kv: -len(kv[1])):
        axes = sorted({s["axis"] for c in cl for s in c["scores"]})
        print(f"  {pid:<18}{len(cl):>3} claims  axes={''.join(axes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
