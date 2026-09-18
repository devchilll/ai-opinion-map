"""The guards that keep the map honest. These are the tests that matter."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.aggregate import ClaimInput, compute, find_contradictions, window_months
from schema.models import EvidenceStatus


def c(cid, doc, d, score, strength=0.9, confidence=0.9, tier=1):
    return ClaimInput(cid, doc, d, score, strength, confidence, tier)


def test_single_claim_is_insufficient():
    """One statement is not a position."""
    out = compute([c("a", "d1", date(2025, 1, 1), 2)], date(2025, 2, 1))
    assert out.status is EvidenceStatus.INSUFFICIENT
    assert out.value is None


def test_empty_window_draws_nothing():
    out = compute([c("a", "d1", date(2019, 1, 1), 3)], date(2025, 1, 1))
    assert out.status is EvidenceStatus.INSUFFICIENT and out.value is None


def test_recent_claims_win_but_history_still_counts():
    """Equal-and-opposite claims 5.5 months apart: the newer side wins, but the
    older side is not erased. That is what a 6-month half-life means, and it is
    what stops the map thrashing on a single fresh interview."""
    old = [c(f"o{i}", f"d{i}", date(2024, 1, 1), -3) for i in range(3)]
    new = [c(f"n{i}", f"e{i}", date(2024, 6, 1), 3) for i in range(3)]
    out = compute(old + new, date(2024, 6, 15))
    assert 0.3 < out.value < 2.0, out.value
    assert out.dispersion > 2.0, "a person saying opposite things should read as blurry"


def test_decay_half_life_is_about_six_months():
    from pipeline.aggregate import LAMBDA_PER_MONTH
    import math
    half_life = math.log(2) / LAMBDA_PER_MONTH
    assert 5.0 < half_life < 7.0, half_life


def test_a_year_old_statement_still_registers():
    """Position at t must not be driven only by the last few weeks."""
    out = compute([c("a", "d1", date(2022, 1, 1), 2), c("b", "d2", date(2022, 3, 1), 2)],
                  date(2022, 11, 1))
    assert out.value is not None


def test_one_document_cannot_outvote_many():
    """14 claims from one essay vs 4 from separate interviews."""
    essay = [c(f"x{i}", "one_essay", date(2025, 1, 1), -3) for i in range(14)]
    spread = [c(f"y{i}", f"doc{i}", date(2025, 1, 1), 3) for i in range(4)]
    out = compute(essay + spread, date(2025, 1, 15))
    assert out.value > 0, f"the long essay won: {out.value}"


def test_tier3_counts_less():
    hi = compute([c("a", "d1", date(2025, 1, 1), 3), c("b", "d2", date(2025, 1, 1), 3)],
                 date(2025, 1, 15))
    lo = compute([c("a", "d1", date(2025, 1, 1), 3, tier=3),
                  c("b", "d2", date(2025, 1, 1), 3, tier=3)], date(2025, 1, 15))
    assert lo.evidence_mass < hi.evidence_mass


def test_disagreement_shows_as_dispersion():
    agree = compute([c(f"a{i}", f"d{i}", date(2025, 1, 1), 2) for i in range(4)], date(2025, 1, 15))
    argue = compute([c("a", "d1", date(2025, 1, 1), 3), c("b", "d2", date(2025, 1, 1), -3),
                     c("c", "d3", date(2025, 1, 1), 3), c("d", "d4", date(2025, 1, 1), -3)],
                    date(2025, 1, 15))
    assert argue.dispersion > agree.dispersion + 1.0


def test_early_years_use_a_wider_window():
    assert window_months(date(2018, 6, 1)) == 24
    assert window_months(date(2022, 6, 1)) == 12
    assert window_months(date(2025, 6, 1)) == 6


def test_2019_claims_survive_to_2020():
    """A wider early window is what makes the 2017 start work at all."""
    claims = [c("a", "d1", date(2019, 3, 1), 2), c("b", "d2", date(2019, 5, 1), 2)]
    out = compute(claims, date(2020, 1, 1))
    assert out.value is not None and out.status is not EvidenceStatus.INSUFFICIENT


def test_contradictions_are_found_not_resolved():
    pairs = find_contradictions([c("a", "d1", date(2025, 1, 1), 3),
                                 c("b", "d2", date(2025, 2, 1), -2)])
    assert pairs and pairs[0][2] == 5
