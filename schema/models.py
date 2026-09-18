"""Canonical schema. Written before any collector runs.

Every collector converts one external format into a Document. No collector
invents a field, and no external schema reaches the database.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    BLOG = "blog"
    ESSAY = "essay"
    POST = "post"
    LETTER = "letter"
    TESTIMONY = "testimony"
    TALK = "talk"
    PODCAST = "podcast"
    INTERVIEW = "interview"
    REPORTING = "reporting"


class Audience(str, Enum):
    PUBLIC_POST = "public_post"
    PODCAST = "podcast"
    CONFERENCE = "conference"
    HEARING = "hearing"
    EARNINGS_CALL = "earnings_call"
    PRESS = "press"


class Axis(str, Enum):
    X = "X"  # Open <-> Closed model access
    Y = "Y"  # Accelerate <-> Precaution
    Z = "Z"  # Incremental <-> Transformative capability
    W = "W"  # Catastrophe <-> Abundance
    S = "S"  # Scale-maximalist <-> Architecture-skeptic (candidate)


class DatePrecision(str, Enum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"


class EvidenceStatus(str, Enum):
    WELL_EVIDENCED = "well_evidenced"
    SPARSE = "sparse"
    INSUFFICIENT = "insufficient"


TIER_WEIGHT = {1: 1.0, 2: 1.0, 3: 0.6, 4: 0.0}
MAX_MAGNITUDE_BY_TIER = {1: 3, 2: 3, 3: 2, 4: 0}


@dataclass
class Person:
    person_id: str
    display_name: str
    headline: bool               # renders as a portrait node
    role: str
    role_verified_on: date | None
    entity_kind: str = "person"  # person | policy | public
    notes: str = ""


@dataclass
class Document:
    """One fetched artifact, converted to canonical form. Immutable once written."""
    doc_id: str                  # sha256 of raw bytes
    person_id: str
    source_url: str
    canonical_url: str
    source_type: SourceType
    source_tier: int
    publisher: str
    title: str
    authored_by_subject: bool
    utterance_date: date | None
    publication_date: date | None
    date_precision: DatePrecision
    language: str
    raw_path: str
    raw_content_hash: str
    text: str
    collector: str
    fetched_at: datetime
    audience: Audience = Audience.PUBLIC_POST
    transcript_segments: list[dict[str, Any]] = field(default_factory=list)
    license_note: str = ""
    access_ok: bool = True
    fetch_error: str = ""
    # Where the date came from and how much we trust it. A collector that gets a
    # date from structured feed metadata sets this itself; the redate pass must
    # not overwrite a date that arrived from a better source than page scraping.
    date_source: str = ""
    date_confidence: str = "none"
    date_note: str = ""

    @staticmethod
    def hash_bytes(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @property
    def effective_date(self) -> date | None:
        """Date of utterance wins over date of publication."""
        return self.utterance_date or self.publication_date


@dataclass
class AxisScore:
    axis: Axis
    score: int                   # -3..+3, integers only
    strength: float              # how directly the quote supports the score
    confidence: float

    def __post_init__(self) -> None:
        if not -3 <= self.score <= 3:
            raise ValueError(f"score {self.score} outside -3..+3")
        if self.score != int(self.score):
            raise ValueError("axis scores are integers")


@dataclass
class Claim:
    """A scored unit of evidence. Cannot exist without supporting_text."""
    claim_id: str
    doc_id: str
    person_id: str
    date: date
    date_precision: DatePrecision
    supporting_text: str         # verbatim, <= 50 words, must appear in Document.text
    normalized_claim: str
    topics: list[str]
    axis_scores: list[AxisScore]
    hedged: bool
    locator: str = ""            # transcript timestamp, paragraph index, or page
    timeline_years: float | None = None   # stated years-to-AGI, when given
    agi_definition: str = ""     # the person's own definition, when given
    corroborating_urls: list[str] = field(default_factory=list)
    extractor_model: str = ""
    rubric_version: str = ""
    extracted_at: datetime | None = None
    human_reviewed: bool = False

    MAX_QUOTE_WORDS = 50

    def __post_init__(self) -> None:
        if not self.supporting_text or not self.supporting_text.strip():
            raise ValueError("no quote, no claim")
        if len(self.supporting_text.split()) > self.MAX_QUOTE_WORDS:
            raise ValueError(
                f"quote is {len(self.supporting_text.split())} words, cap is {self.MAX_QUOTE_WORDS}"
            )


@dataclass
class Event:
    event_id: str
    date: date
    date_precision: DatePrecision
    title: str                   # <= 60 chars
    summary: str
    category: str                # Models|Research|Companies|Leadership|Capital|
                                 # Infrastructure|Commercial|Policy|Labor|Scaling
    importance: int              # 1..5
    people: list[str]
    orgs: list[str]
    sources: list[str]           # >= 2 independent reputable sources
    ai_attributed_by_company: bool | None = None  # Labor events only

    def __post_init__(self) -> None:
        if len(self.sources) < 2:
            raise ValueError("events need two independent sources")
        if not 1 <= self.importance <= 5:
            raise ValueError("importance is 1..5")


@dataclass
class Poll:
    """Public opinion. Survey data, never scraped sentiment."""
    poll_id: str
    pollster: str
    series_id: str
    field_start: date
    field_end: date
    population: str
    n: int
    question_text: str
    results: dict[str, float]
    axis: Axis
    mapped_score: float
    mapping_note: str
    source_url: str
    margin_of_error: float | None = None
    wording_changed_from_prior: bool = False


@dataclass
class Position:
    """A rendered coordinate. Never exists without evidence behind it."""
    person_id: str
    axis: Axis
    at_month: str                # YYYY-MM
    value: float | None          # None when status is INSUFFICIENT
    n_claims: int
    evidence_mass: float
    dispersion: float
    status: EvidenceStatus
    contributing_claim_ids: list[str] = field(default_factory=list)


def to_row(obj: Any) -> dict[str, Any]:
    """Flatten a dataclass for sqlite, JSON-encoding nested structures."""
    import json
    row: dict[str, Any] = {}
    for k, v in asdict(obj).items():
        if isinstance(v, (list, dict)):
            row[k] = json.dumps(v, default=str)
        elif isinstance(v, (date, datetime)):
            row[k] = v.isoformat()
        elif isinstance(v, Enum):
            row[k] = v.value
        else:
            row[k] = v
    return row
