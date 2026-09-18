"""Ingest hand-extracted claims through the SAME validator models face.

Used for the gold/calibration set and for claims extracted by an agent in the
loop. There is no privileged path into the claims table: a quote that is not
verbatim in the source document is rejected here exactly as it would be if a
model had produced it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import connect  # noqa: E402
from pipeline.extract import (RUBRIC_VERSION, normalize, quote_is_verbatim,  # noqa: E402
                              quote_too_long, save)
from schema.models import Axis, MAX_MAGNITUDE_BY_TIER  # noqa: E402


def build(records: list[dict], extractor: str) -> tuple[list[dict], list[str]]:
    rejected: list[str] = []
    out: list[dict] = []
    with connect() as conn:
        docs = {r["doc_id"]: dict(r) for r in conn.execute(
            "SELECT doc_id, person_id, text, publication_date, date_precision, source_tier "
            "FROM documents")}

    for rec in records:
        doc = docs.get(rec["doc_id"])
        if not doc:
            rejected.append(f"unknown doc_id {rec['doc_id'][:12]}")
            continue
        quote = rec["supporting_text"].strip()
        if not quote_is_verbatim(quote, doc["text"]):
            rejected.append(f"NOT VERBATIM: {quote[:64]!r}")
            continue
        if quote_too_long(quote):
            rejected.append(f"quote too long: {quote[:48]!r}")
            continue

        cap = MAX_MAGNITUDE_BY_TIER.get(doc["source_tier"], 3)
        scores = []
        for sc in rec.get("axis_scores") or []:
            score = max(-cap, min(cap, int(sc["score"])))
            if rec.get("hedged"):
                score = max(-1, min(1, score))
            scores.append({"axis": Axis(sc["axis"]).value, "score": score,
                           "strength": float(sc.get("strength", 0.8)),
                           "confidence": float(sc.get("confidence", 0.8))})

        out.append({
            "claim_id": hashlib.sha1(
                f"{doc['doc_id']}|{normalize(quote)}".encode()).hexdigest()[:24],
            "doc_id": doc["doc_id"], "person_id": doc["person_id"],
            "date": str(doc["publication_date"])[:10],
            "date_precision": doc["date_precision"],
            "supporting_text": quote,
            "normalized_claim": rec.get("normalized_claim", "")[:400],
            "topics": json.dumps(rec.get("topics") or []),
            "axis_scores": json.dumps(scores),
            "hedged": int(bool(rec.get("hedged"))),
            "locator": rec.get("locator", ""),
            "timeline_years": rec.get("timeline_years"),
            "agi_definition": rec.get("agi_definition", ""),
            "corroborating_urls": "[]",
            "extractor_model": extractor, "rubric_version": RUBRIC_VERSION,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "human_reviewed": int(bool(rec.get("human_reviewed"))),
        })
    return out, rejected


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--extractor", default="agent:claude-opus-5")
    args = ap.parse_args()

    records = json.loads(Path(args.path).read_text())
    claims, rejected = build(records, args.extractor)
    for r in rejected:
        print(f"  REJECTED  {r}")
    inserted = save(claims)
    print(f"\n{len(claims)} validated, {len(rejected)} rejected, {inserted} new rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
