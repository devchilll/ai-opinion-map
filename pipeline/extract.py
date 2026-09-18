"""Document -> atomic claims, each carrying a verbatim quote and axis scores.

The contract: NO belief classification without supporting source text. Anything
the model returns whose quote cannot be found verbatim in the document is
discarded, loudly. That is what makes a small local model usable here -- its
failure mode becomes a dropped claim rather than an invented one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import llm  # noqa: E402
from pipeline.db import connect  # noqa: E402
from schema.models import Axis, MAX_MAGNITUDE_BY_TIER  # noqa: E402

RUBRIC_VERSION = "2026-09-17.1"
MAX_QUOTE_WORDS = 50
# Chinese and Japanese text has no spaces, so a word count is meaningless there:
# a 300-character quote splits into one "word" and sails past the cap.
MAX_QUOTE_CJK_CHARS = 120
WINDOW_CHARS = 5000

RUBRIC = """You extract PUBLICLY EXPRESSED POSITIONS about AI from a document.

Score only on these axes, each an integer from -3 to +3:

X  Model access.  -3 frontier weights should be released openly; +3 frontier
   release should be restricted by policy or law. 0 = explicitly balanced.
Y  Development posture.  -3 build and deploy faster, slowing down is the danger;
   +3 supports pauses or halting frontier development. +1/+2 = evals, binding
   pre-deployment requirements, licensing.
Z  Transformative capability belief.  -3 current methods will not get there,
   overhyped; +3 superintelligence or civilization-scale discontinuity, soon.
   This measures HOW BIG they think it gets, NOT whether that is good or bad.
W  Expected outcome.  -3 catastrophe is the likely default; +3 radical abundance.
S  Path.  -3 scale-maximalist (more compute and tokens is the road);
   +3 architecture-skeptic (scaling alone will not get there).

Rules:
- supporting_text MUST be copied EXACTLY, character for character, from the
  document. Never paraphrase it. Never repair grammar. Maximum 50 words.
- Extract only statements of the author's own position. Skip descriptions of
  what others think, product marketing, and neutral background.
- Hedged or conditional phrasing caps magnitude at 1.
- If a passage states a timeline to AGI or transformative AI, set
  timeline_years to the number of years from the time of writing.
- Return [] when the passage contains no expressed position. That is common
  and correct.

Return ONLY a JSON array, no prose:
[{"supporting_text":"exact quote","normalized_claim":"one neutral sentence",
  "topics":["open_weights"],"axis_scores":[{"axis":"X","score":-2,
  "strength":0.8,"confidence":0.9}],"hedged":false,"timeline_years":null}]"""


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def cjk_chars(s: str) -> int:
    return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff")


def quote_too_long(quote: str) -> bool:
    if cjk_chars(quote) > 0:
        return cjk_chars(quote) > MAX_QUOTE_CJK_CHARS
    return len(quote.split()) > MAX_QUOTE_WORDS


def quote_is_verbatim(quote: str, document_text: str) -> bool:
    """The single most important check in the pipeline."""
    return bool(quote.strip()) and normalize(quote) in normalize(document_text)


def windows(text: str, size: int = WINDOW_CHARS, overlap: int = 500):
    step = size - overlap
    for i in range(0, max(1, len(text)), step):
        chunk = text[i:i + size]
        if len(chunk.split()) > 60:
            yield chunk


def extract_document(doc: dict, *, verbose: bool = False) -> tuple[list[dict], dict]:
    text = doc["text"] or ""
    cap = MAX_MAGNITUDE_BY_TIER.get(doc["source_tier"], 3)
    claims: list[dict] = []
    stats = {"returned": 0, "rejected_unverbatim": 0, "rejected_shape": 0, "kept": 0}

    for chunk in windows(text):
        prompt = f"{RUBRIC}\n\n---DOCUMENT---\n{chunk}\n---END---\n\nJSON array:"
        try:
            parsed = llm.parse_json(llm.complete(prompt))
        except Exception as exc:
            print(f"    llm error: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(parsed, list):
            continue

        for item in parsed:
            stats["returned"] += 1
            if not isinstance(item, dict):
                stats["rejected_shape"] += 1
                continue
            quote = (item.get("supporting_text") or "").strip()

            if not quote_is_verbatim(quote, text):
                stats["rejected_unverbatim"] += 1
                if verbose:
                    print(f"    REJECTED (not in source): {quote[:70]!r}")
                continue
            if quote_too_long(quote):
                stats["rejected_shape"] += 1
                continue

            scores = []
            for sc in item.get("axis_scores") or []:
                try:
                    axis = Axis(str(sc["axis"]).upper())
                    score = int(round(float(sc["score"])))
                except (KeyError, ValueError, TypeError):
                    continue
                score = max(-cap, min(cap, score))
                if item.get("hedged"):
                    score = max(-1, min(1, score))
                scores.append({
                    "axis": axis.value, "score": score,
                    "strength": float(sc.get("strength", 0.7) or 0.7),
                    "confidence": float(sc.get("confidence", 0.7) or 0.7),
                })
            if not scores:
                stats["rejected_shape"] += 1
                continue

            claims.append({
                "claim_id": hashlib.sha1(
                    f"{doc['doc_id']}|{normalize(quote)}".encode()).hexdigest()[:24],
                "doc_id": doc["doc_id"], "person_id": doc["person_id"],
                "date": str(doc["publication_date"])[:10],
                "date_precision": doc["date_precision"],
                "supporting_text": quote,
                "normalized_claim": (item.get("normalized_claim") or "")[:400],
                "topics": json.dumps(item.get("topics") or []),
                "axis_scores": json.dumps(scores),
                "hedged": int(bool(item.get("hedged"))),
                "locator": "", "timeline_years": item.get("timeline_years"),
                "agi_definition": "", "corroborating_urls": "[]",
                "extractor_model": llm.describe(), "rubric_version": RUBRIC_VERSION,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "human_reviewed": 0,
            })
            stats["kept"] += 1
    return claims, stats


def save(claims: list[dict]) -> int:
    if not claims:
        return 0
    cols = list(claims[0].keys())
    sql = (f"INSERT OR IGNORE INTO claims ({','.join(cols)}) "
           f"VALUES ({','.join('?' for _ in cols)})")
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        conn.executemany(sql, [tuple(c[k] for k in cols) for c in claims])
        after = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    return after - before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--person", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    q = ("SELECT doc_id, person_id, text, publication_date, date_precision, source_tier, title "
         "FROM documents WHERE date_confidence IN ('high','medium') AND authored_by_subject=1 ")
    params: list = []
    if args.person:
        q += "AND person_id=? "
        params.append(args.person)
    q += "ORDER BY publication_date DESC LIMIT ?"
    params.append(args.limit)

    with connect() as conn:
        docs = [dict(r) for r in conn.execute(q, params)]

    print(f"model: {llm.describe()}  |  {len(docs)} documents\n")
    total = {"returned": 0, "rejected_unverbatim": 0, "rejected_shape": 0, "kept": 0}
    for d in docs:
        print(f"  {d['person_id']:<18}{str(d['publication_date'])[:10]}  {(d['title'] or '')[:46]}")
        claims, stats = extract_document(d, verbose=args.verbose)
        for k in total:
            total[k] += stats[k]
        print(f"    kept {stats['kept']}, rejected {stats['rejected_unverbatim']} "
              f"for unverbatim quotes, {stats['rejected_shape']} malformed")
        save(claims)

    print(f"\nTOTAL {total}")
    if total["returned"]:
        pct = 100 * total["rejected_unverbatim"] / total["returned"]
        print(f"hallucinated-quote rate: {pct:.1f}%  (all caught and discarded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
