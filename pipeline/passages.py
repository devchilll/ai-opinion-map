"""Relevant passage detection: find the sentences worth scoring.

A 15,000-word interview contains perhaps twenty sentences that state a position
on our axes. This pulls those out, with enough surrounding text to judge
context and speaker, so an extractor (model or human) reads 5% of the document
instead of all of it.

Purely lexical on purpose: no embeddings, no model, deterministic, auditable.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import connect  # noqa: E402

AXIS_TERMS = {
    "X": r"open[- ]?sourc|open[- ]?weight|closed[- ]?(source|model)|proprietary|release (the )?weights|open models?|api[- ]only",
    "Y": r"regulat|pause|moratorium|slow(ing)? down|safety|evals?\b|licens|oversight|guardrail|government|legislat|SB ?1047|executive order",
    "Z": r"\bAGI\b|superintelligen|transformative|recursive|self[- ]improv|timeline|within (\d+|a few|five|ten) years|by 20[2-3]\d|automate|end of the exponential|country of geniuses",
    "W": r"existential|extinction|catastroph|\bdoom|abundance|cure (all )?disease|poverty|utopia|kill (us|everyone)|p\(doom\)|lift .* out of poverty",
    "S": r"scaling (law|hypothesis)|scale is all|hit(ting)? a wall|world models?|LLMs? (can'?t|won'?t|will never|are not)|next[- ]token prediction|more (compute|data) (won'?t|will|is)|pre-?training (is|has)|diminishing returns|new (architecture|paradigm)|bitter lesson",
}
_RX = {a: re.compile(p, re.I) for a, p in AXIS_TERMS.items()}
_SENT = re.compile(r"(?<=[.!?。！？])\s+")


def passages(text: str, *, context: int = 1, max_out: int = 40) -> list[tuple[str, str]]:
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    hits: list[tuple[int, str]] = []
    for i, s in enumerate(sents):
        axes = "".join(a for a, rx in _RX.items() if rx.search(s))
        if axes:
            hits.append((i, axes))
    # merge neighbours, keep order, cap
    out, used = [], set()
    for i, axes in hits:
        if i in used:
            continue
        lo, hi = max(0, i - context), min(len(sents), i + context + 1)
        used.update(range(lo, hi))
        out.append((axes, " ".join(sents[lo:hi])))
        if len(out) >= max_out:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--collector", default=None)
    args = ap.parse_args()

    q = ("SELECT doc_id, title, publication_date, source_tier, text, canonical_url FROM documents "
         "WHERE person_id=? AND authored_by_subject=1 AND date_confidence IN ('high','medium')")
    params = [args.person]
    if args.collector:
        q += " AND collector=?"
        params.append(args.collector)
    q += " ORDER BY publication_date DESC"

    with connect() as conn:
        docs = [dict(r) for r in conn.execute(q, params)]
    for d in docs:
        ps = passages(d["text"], max_out=args.max)
        print(f"\n### {d['doc_id'][:12]}  {str(d['publication_date'])[:10]}  tier{d['source_tier']}  "
              f"{(d['title'] or '')[:70]}\n    {d['canonical_url']}")
        for axes, p in ps:
            print(f"  [{axes:<4}] {p[:420]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
