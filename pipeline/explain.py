"""Show exactly how one coordinate was produced, quote by quote.

No embeddings anywhere in this chain. A coordinate is a weighted mean of
integer rubric scores, each attached to a dated verbatim quote.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.aggregate import (DOC_CAP_CLAIMS, LAMBDA_PER_MONTH, ClaimInput,  # noqa: E402
                                _months_between, compute, window_months)
from pipeline.db import connect  # noqa: E402
from schema.models import TIER_WEIGHT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True)
    ap.add_argument("--axis", required=True)
    ap.add_argument("--at", required=True, help="YYYY-MM")
    args = ap.parse_args()
    at = date(int(args.at[:4]), int(args.at[5:7]), 1)

    with connect() as conn:
        rows = [dict(r) for r in conn.execute("""
            SELECT c.claim_id, c.doc_id, c.date, c.supporting_text, c.axis_scores,
                   c.hedged, d.source_tier, d.title, d.canonical_url
            FROM claims c JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.person_id = ? AND d.date_confidence IN ('high','medium')
            ORDER BY c.date""", (args.person,))]

    claims, detail = [], {}
    for r in rows:
        for sc in json.loads(r["axis_scores"] or "[]"):
            if sc["axis"] != args.axis:
                continue
            ci = ClaimInput(r["claim_id"], r["doc_id"],
                            date.fromisoformat(str(r["date"])[:10]),
                            int(sc["score"]), float(sc["strength"]),
                            float(sc["confidence"]), int(r["source_tier"]))
            claims.append(ci)
            detail[r["claim_id"]] = (r, sc)

    win = window_months(at)
    print(f"position({args.person}, {args.axis}, {args.at})\n")
    print(f"  lookback window : {win} months")
    print(f"  decay           : lambda={LAMBDA_PER_MONTH}/month "
          f"(half-life {math.log(2)/LAMBDA_PER_MONTH:.1f} months)")
    print(f"  per-document cap: {DOC_CAP_CLAIMS} claims of weight\n")
    print(f"  {len(claims)} scored claim(s) on this axis in the corpus\n")

    contributing = []
    for ci in claims:
        age = _months_between(ci.date, at)
        inside = 0 <= age <= win
        w = (ci.strength * ci.confidence * TIER_WEIGHT.get(ci.tier, 0.0)
             * math.exp(-LAMBDA_PER_MONTH * age)) if inside else 0.0
        r, sc = detail[ci.claim_id]
        mark = "IN " if inside else "out"
        print(f"  [{mark}] {ci.date}  score={ci.score:+d}  age={age:5.1f}mo  weight={w:.3f}")
        print(f"        \"{r['supporting_text'][:88]}\"")
        print(f"        strength={ci.strength} x confidence={ci.confidence} "
              f"x tier{ci.tier}={TIER_WEIGHT.get(ci.tier)} x e^(-{LAMBDA_PER_MONTH}*{age:.1f})")
        print(f"        {r['canonical_url']}")
        if inside:
            contributing.append((ci, w))
        print()

    if contributing:
        num = sum(c.score * w for c, w in contributing)
        den = sum(w for _, w in contributing)
        print(f"  weighted mean = {num:.3f} / {den:.3f} = {num/den:+.3f}   <-- the coordinate")

    out = compute(claims, at)
    print(f"\n  aggregate -> value={out.value} status={out.status.value} "
          f"n={out.n_claims} mass={out.evidence_mass} dispersion={out.dispersion}")
    if out.value is None:
        print("  value is None: not enough evidence, so nothing is drawn on this axis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
