"""Claims -> position(person, axis, month).

The formula from the spec, with the guards that keep it honest:
  - exponential decay, half-life ~6 months
  - lookback window widens in the sparse early years
  - per-document weight cap, so one long essay cannot outvote a year of interviews
  - uncertainty is a stored output, not an afterthought
  - an under-evidenced axis returns status=insufficient and value=None, and the
    renderer must not draw a coordinate for it
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from schema.models import Axis, EvidenceStatus, TIER_WEIGHT

LAMBDA_PER_MONTH = 0.12          # ~6 month half-life
DOC_CAP_CLAIMS = 3.0             # a single document contributes at most ~3 claims of weight
MIN_CLAIMS = 2
MIN_EVIDENCE_MASS = 0.35
SPARSE_EVIDENCE_MASS = 1.2

# When the base window holds too little, widen it step by step rather than
# drawing nothing. A 2024 interview is the best available evidence for someone
# in 2026 if they have said nothing newer -- but the UI must then say so, which
# is what `newest_age_months` is for.
WINDOW_STEPS = (6, 12, 24, 36)
MAX_WINDOW = WINDOW_STEPS[-1]


def window_months(at: date) -> int:
    """Wider lookback in the sparse years, tighter as source density rises."""
    if at.year <= 2020:
        return 24
    if at.year <= 2023:
        return 12
    return 6


@dataclass
class ClaimInput:
    claim_id: str
    doc_id: str
    date: date
    score: int
    strength: float
    confidence: float
    tier: int


@dataclass
class PositionOut:
    value: float | None
    n_claims: int
    evidence_mass: float
    dispersion: float
    status: EvidenceStatus
    contributing_claim_ids: list[str]
    window_months: int = 0          # the lookback that was actually used
    newest_age_months: float = 0.0  # how stale the freshest contributing claim is


def _months_between(earlier: date, later: date) -> float:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month) + \
           (later.day - earlier.day) / 30.44


def compute(claims: list[ClaimInput], at: date) -> PositionOut:
    base = window_months(at)
    decay = LAMBDA_PER_MONTH if at.year >= 2021 else LAMBDA_PER_MONTH / 2

    aged = [(c, _months_between(c.date, at)) for c in claims]
    aged = [(c, a) for c, a in aged if a >= 0]

    # Widen until the window holds enough distinct documents to call a position.
    window = base
    in_window: list = []
    for step in [w for w in WINDOW_STEPS if w >= base] or [base]:
        window = step
        in_window = [(c, a) for c, a in aged if a <= window]
        if len({c.doc_id for c, _ in in_window}) >= MIN_CLAIMS:
            break

    if not in_window:
        return PositionOut(None, 0, 0.0, 0.0, EvidenceStatus.INSUFFICIENT, [], window, 0.0)

    newest_age = min(a for _, a in in_window)

    # Raw weights, then normalise within each document so a long essay that
    # yielded 14 claims does not outvote 14 separate interviews.
    raw: dict[str, list[tuple[ClaimInput, float]]] = defaultdict(list)
    for c, age in in_window:
        w = (c.strength * c.confidence * TIER_WEIGHT.get(c.tier, 0.0)
             * math.exp(-decay * (age - newest_age)))
        raw[c.doc_id].append((c, w))

    weighted: list[tuple[ClaimInput, float]] = []
    for _doc_id, items in raw.items():
        total = sum(w for _, w in items)
        if total <= 0:
            continue
        mean_w = total / len(items)
        cap = DOC_CAP_CLAIMS * mean_w
        scale = min(1.0, cap / total)
        weighted += [(c, w * scale) for c, w in items]

    mass = sum(w for _, w in weighted)
    if mass <= 0:
        return PositionOut(None, 0, 0.0, 0.0, EvidenceStatus.INSUFFICIENT, [], window, 0.0)

    value = sum(c.score * w for c, w in weighted) / mass
    if len(weighted) > 1:
        var = sum(w * (c.score - value) ** 2 for c, w in weighted) / mass
        dispersion = math.sqrt(var)
    else:
        dispersion = 0.0

    n = len(weighted)
    n_docs = len({c.doc_id for c, _ in weighted})
    # Two claims from ONE document is still one occasion, not a position.
    if n < MIN_CLAIMS or n_docs < MIN_CLAIMS or mass < MIN_EVIDENCE_MASS:
        status = EvidenceStatus.INSUFFICIENT
        value = None
    elif mass < SPARSE_EVIDENCE_MASS or newest_age > 18:
        status = EvidenceStatus.SPARSE          # also covers "evidence is stale"
    else:
        status = EvidenceStatus.WELL_EVIDENCED

    return PositionOut(
        value=round(value, 3) if value is not None else None,
        n_claims=n, evidence_mass=round(mass, 4), dispersion=round(dispersion, 3),
        status=status, contributing_claim_ids=[c.claim_id for c, _ in weighted],
        window_months=window, newest_age_months=round(newest_age, 1),
    )


def find_contradictions(claims: list[ClaimInput], *, span_days: int = 90,
                        min_gap: int = 3) -> list[tuple[str, str, int]]:
    """Pairs of claims close in time whose scores disagree sharply.

    Contradictions are surfaced with both receipts, never resolved away.
    """
    out = []
    ordered = sorted(claims, key=lambda c: c.date)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if (b.date - a.date).days > span_days:
                break
            gap = abs(a.score - b.score)
            if gap >= min_gap:
                out.append((a.claim_id, b.claim_id, gap))
    return out


def axis_diagnostics(positions: dict[str, dict[Axis, float | None]]) -> dict:
    """Variance and pairwise correlation across people. Gates the 3D view."""
    axes = [a for a in Axis]
    series = {a: [p[a] for p in positions.values() if p.get(a) is not None] for a in axes}
    diag: dict = {"variance": {}, "n_scoreable": {}, "correlations": {}}
    for a in axes:
        vals = series[a]
        diag["n_scoreable"][a.value] = len(vals)
        diag["variance"][a.value] = round(statistics.pvariance(vals), 3) if len(vals) > 1 else 0.0

    for i, a in enumerate(axes):
        for b in axes[i + 1:]:
            paired = [(p[a], p[b]) for p in positions.values()
                      if p.get(a) is not None and p.get(b) is not None]
            if len(paired) > 2:
                xs, ys = zip(*paired)
                try:
                    diag["correlations"][f"{a.value}-{b.value}"] = round(
                        statistics.correlation(xs, ys), 3)
                except statistics.StatisticsError:
                    pass
    return diag
