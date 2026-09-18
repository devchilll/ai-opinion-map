"""Build monthly positions for every person and axis, 2017-01 .. now.

Writes data/out/positions.json, which is the only thing the web app consumes.
Positions are precomputed here so the timeline scrubber is instant and the app
needs no backend.

Also supports --synthetic: a clearly-labelled fixture so the visualisation can
be built and judged before claim extraction is unblocked. Synthetic output
carries synthetic:true and the app must refuse to hide that.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.aggregate import ClaimInput, axis_diagnostics, compute, find_contradictions  # noqa: E402
from pipeline.db import connect  # noqa: E402
from schema.models import Axis, EvidenceStatus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "out" / "positions.json"
START = date(2017, 1, 1)


def months(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_registry() -> tuple[list[dict], dict[str, list[str]]]:
    reg = yaml.safe_load((ROOT / "data" / "registry" / "people.yaml").read_text())
    allowed = {p["person_id"]: p.get("axes_allowed") or [a.value for a in Axis]
               for p in reg["people"]}
    return reg["people"], allowed


def load_claims() -> dict[tuple[str, str], list[ClaimInput]]:
    """Real claims from the database, keyed by (person_id, axis).

    Only documents whose date we actually trust are eligible: a claim with an
    unreliable date would be placed in the wrong month, which is worse than
    being absent.
    """
    by: dict[tuple[str, str], list[ClaimInput]] = {}
    with connect() as conn:
        rows = conn.execute("""
            SELECT c.claim_id, c.doc_id, c.person_id, c.date, c.axis_scores, d.source_tier
            FROM claims c JOIN documents d ON d.doc_id = c.doc_id
            WHERE d.date_confidence IN ('high','medium')
        """).fetchall()
    for r in rows:
        d = date.fromisoformat(str(r["date"])[:10])
        for s in json.loads(r["axis_scores"] or "[]"):
            by.setdefault((r["person_id"], s["axis"]), []).append(
                ClaimInput(r["claim_id"], r["doc_id"], d, int(s["score"]),
                           float(s.get("strength", 1.0)), float(s.get("confidence", 1.0)),
                           int(r["source_tier"])))
    return by


def synthetic_claims(people: list[dict], allowed: dict[str, list[str]], seed: int = 7):
    """A fixture with the shapes the real data will have: staggered entry,
    sparse early years, drift, and some genuine disagreement."""
    rng = random.Random(seed)
    by: dict[tuple[str, str], list[ClaimInput]] = {}
    today = date.today()
    for p in people:
        pid = p["person_id"]
        starts = str(p.get("evidence_starts", "2017-01"))
        start = date(int(starts[:4]), int(starts[5:7]), 1)
        drift = {a: rng.uniform(-0.05, 0.08) for a in allowed[pid]}
        base = {a: rng.uniform(-2, 2) for a in allowed[pid]}
        for i, m in enumerate(months(start, today)):
            density = 0.25 if m.year <= 2020 else (0.6 if m.year <= 2022 else 0.95)
            if rng.random() > density:
                continue
            for a in allowed[pid]:
                if rng.random() > 0.55:
                    continue
                target = base[a] + drift[a] * i
                for k in range(rng.randint(1, 3)):
                    score = max(-3, min(3, round(target + rng.gauss(0, 0.9))))
                    by.setdefault((pid, a), []).append(
                        ClaimInput(f"syn-{pid}-{a}-{i}-{k}", f"syndoc-{pid}-{i}",
                                   date(m.year, m.month, rng.randint(1, 28)),
                                   int(score), 0.85, 0.85, 1))
    return by


def load_events() -> list[dict]:
    """Verified events only. An event with no live citation is an assertion."""
    path = ROOT / "data" / "registry" / "events.yaml"
    if not path.exists():
        return []
    rows = yaml.safe_load(path.read_text())["events"]
    return [{
        "id": e["id"], "date": str(e["date"]), "title": e["title"],
        "summary": " ".join(e["summary"].split()), "category": e["category"],
        "importance": e["importance"], "people": e.get("people") or [],
        "sources": e["sources"],
    } for e in rows if e.get("verified")]


def build(synthetic: bool) -> dict:
    people, allowed = load_registry()
    claims = synthetic_claims(people, allowed) if synthetic else load_claims()
    today = date.today()
    grid = months(START, today)

    out_people = []
    latest: dict[str, dict] = {}
    for p in people:
        pid = p["person_id"]
        series: dict[str, list] = {}
        for axis in allowed[pid]:
            cl = claims.get((pid, axis), [])
            row = []
            for m in grid:
                pos = compute(cl, m)
                row.append(None if pos.value is None else
                           [round(pos.value, 2), round(pos.dispersion, 2),
                            pos.n_claims, pos.status.value[0]])
            series[axis] = row
        contradictions = sum(len(find_contradictions(claims.get((pid, a), [])))
                             for a in allowed[pid])
        first_idx = min((i for a in series for i, v in enumerate(series[a]) if v),
                        default=None)
        out_people.append({
            "id": pid, "name": p["display_name"], "role": p.get("role", ""),
            "kind": p.get("entity_kind", "person"),
            "headline": bool(p.get("headline")),
            # Axes this entity can honestly occupy. An axis absent here is
            # structurally undefined (nobody polls the public on open weights;
            # politicians state policy, not capability beliefs) and renders as a
            # line through that dimension rather than a false point.
            "axes_allowed": list(allowed[pid]),
            "notes": p.get("notes", ""),
            "axes": series,
            "enters_at": grid[first_idx].isoformat()[:7] if first_idx is not None else None,
            "contradictions": contradictions,
        })
        latest[pid] = {Axis(a): (series[a][-1][0] if series[a][-1] else None)
                       for a in allowed[pid]}

    return {
        "synthetic": synthetic,
        "generated_at": today.isoformat(),
        "months": [m.isoformat()[:7] for m in grid],
        "axes": {
            "X": {"label": "Model access", "low": "Open", "high": "Closed"},
            "Y": {"label": "Development posture", "low": "Accelerate", "high": "Precaution"},
            "Z": {"label": "How AGI-pilled", "low": "Incremental", "high": "Civilization-scale"},
            "W": {"label": "Expected outcome", "low": "Catastrophe", "high": "Abundance"},
            "S": {"label": "Path", "low": "Scale-maximalist", "high": "Architecture-skeptic"},
        },
        "people": out_people,
        "events": load_events(),
        "diagnostics": axis_diagnostics(latest),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true",
                    help="labelled fixture for building the visualisation")
    args = ap.parse_args()

    data = build(args.synthetic)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))

    drawn = sum(1 for p in data["people"] for a in p["axes"] if p["axes"][a][-1])
    print(f"{'SYNTHETIC ' if args.synthetic else ''}positions -> {OUT}")
    print(f"  {len(data['people'])} people, {len(data['months'])} months, "
          f"{OUT.stat().st_size // 1024} KB")
    print(f"  {drawn} person-axes currently drawable")
    print(f"  {len(data['events'])} verified events on the timeline")
    print(f"  diagnostics: {json.dumps(data['diagnostics']['correlations'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
