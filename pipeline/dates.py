"""Date extraction, with a confidence level attached.

Dates are the spine of this project: every coordinate is a function of time, so
a wrong date is worse than a missing one. The first collector run proved it --
a generic metadata extractor dated "Machines of Loving Grace" to 2015 when the
page says October 2024 under the title, and stamped 14 unrelated posts with one
site-wide date.

Strategy: run several independent extractors, prefer the visible dateline a
human would read, and cross-check them. Agreement raises confidence,
disagreement lowers it. Record which strategy won so a bad run is debuggable.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from dateutil import parser as dateparser

HIGH, MEDIUM, LOW, NONE = "high", "medium", "low", "none"

_URL_DATE = re.compile(r"/(20[0-2]\d)[/-](0?[1-9]|1[0-2])(?:[/-](0?[1-9]|[12]\d|3[01]))?(?:/|$|-)")
_JSONLD = re.compile(r'"date[Pp]ublished"\s*:\s*"([^"]{4,40})"')
_TIME_TAG = re.compile(r'<time[^>]+datetime=["\']([^"\']{4,40})["\']', re.I)
_META = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|citation_publication_date|'
    r'DC\.date\.issued|pubdate)["\'][^>]+content=["\']([^"\']{4,40})["\']', re.I)
_MONTH_YEAR = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2},?\s*)?(20[0-2]\d)\b")
_ISO_IN_TEXT = re.compile(r"\b(20[0-2]\d)-(\d{2})-(\d{2})\b")

MIN_YEAR, MAX_YEAR = 1990, 2030
DATELINE_WINDOW = 700          # chars of visible text a dateline realistically sits in


@dataclass
class DateGuess:
    value: date | None
    precision: str          # day | month | quarter
    source: str             # url | jsonld | dateline | time_tag | meta | body | none
    confidence: str         # high | medium | low | none
    note: str = ""

    @property
    def trustworthy(self) -> bool:
        return self.confidence in (HIGH, MEDIUM)


def visible_text(html: str) -> str:
    s = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def _parse(raw: str) -> date | None:
    try:
        d = dateparser.parse(raw, fuzzy=False).date()
    except (ValueError, TypeError, OverflowError):
        return None
    return d if MIN_YEAR <= d.year <= MAX_YEAR else None


def _candidates(html: str, url: str) -> list[tuple[date, str, str]]:
    """Every independent reading of this page's date: (date, precision, source)."""
    out: list[tuple[date, str, str]] = []

    m = _URL_DATE.search(url)
    if m:
        try:
            out.append((date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)),
                        "day" if m.group(3) else "month", "url"))
        except ValueError:
            pass

    text = visible_text(html)
    head = text[:DATELINE_WINDOW]
    m = _MONTH_YEAR.search(head)
    if m:
        d = _parse(m.group(0))
        if d:
            out.append((d, "day" if m.group(2) else "month", "dateline"))
    else:
        m = _ISO_IN_TEXT.search(head)
        if m and (d := _parse(m.group(0))):
            out.append((d, "day", "dateline"))

    for pattern, source in ((_JSONLD, "jsonld"), (_TIME_TAG, "time_tag"), (_META, "meta")):
        for cand in pattern.findall(html)[:4]:
            if d := _parse(cand):
                out.append((d, "day", source))
                break

    m = _MONTH_YEAR.search(text[:6000])
    if m and (d := _parse(m.group(0))):
        out.append((d, "day" if m.group(2) else "month", "body"))

    return out


# The visible dateline outranks metadata: publishers get their own <meta> wrong
# far more often than they get the line under the headline wrong.
_RANK = {"feed": 0, "url": 1, "dateline": 2, "jsonld": 3, "time_tag": 4, "meta": 5, "body": 6}
_BASE_CONFIDENCE = {"feed": HIGH, "url": HIGH, "dateline": HIGH, "jsonld": MEDIUM,
                    "time_tag": MEDIUM, "meta": MEDIUM, "body": LOW}

# Corroboration only counts between independent readings. "dateline" and "body"
# are the same extractor looking at the same visible text, so one agreeing with
# the other proves nothing.
_FAMILY = {"feed": "structured", "url": "structured", "jsonld": "structured", "time_tag": "structured",
           "meta": "structured", "dateline": "text", "body": "text"}


def extract(html: str, url: str, feed_date: str | None = None) -> DateGuess:
    cands = _candidates(html, url)
    if feed_date:
        try:
            cands.insert(0, (date.fromisoformat(feed_date[:10]), "day", "feed"))
        except ValueError:
            pass
    if not cands:
        return DateGuess(None, "quarter", "none", NONE)

    cands.sort(key=lambda c: _RANK[c[2]])
    best_date, precision, source = cands[0]
    confidence = _BASE_CONFIDENCE[source]
    note = ""

    others = [c for c in cands[1:] if _FAMILY[c[2]] != _FAMILY[source]]
    if others:
        gaps = [abs((best_date - d).days) for d, _, _ in others]
        if min(gaps) <= 45:
            confidence = HIGH
            note = f"corroborated by {others[gaps.index(min(gaps))][2]}"
        elif min(gaps) > 400:
            confidence = LOW if confidence == HIGH else confidence
            note = f"conflicts with {others[0][2]} ({others[0][0]}) by {min(gaps)}d"

    # Month-precision dates must not pretend to a day. dateutil fills the gap
    # with today's day number, which silently invents precision.
    if precision == "month":
        best_date = best_date.replace(day=1)

    # A dateline resolving to the current month is usually site furniture --
    # a nav label or a "latest posts" header, not this document's date.
    today = date.today()
    if (best_date.year, best_date.month) == (today.year, today.month) and "corroborated" not in note:
        confidence = LOW
        note = (note + "; " if note else "") + "resolves to current month, likely site furniture"

    return DateGuess(best_date, precision, source, confidence, note)


def downgrade_clustered(rows: list[dict], *, threshold: int = 4) -> dict[str, str]:
    """A date repeated across many documents from one host is site furniture."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("publication_date") and r.get("date_source") != "url":
            u = r.get("canonical_url") or ""
            host = u.split("/")[2] if "//" in u else ""
            buckets[(host, str(r["publication_date"])[:10])].append(r)
    return {r["doc_id"]: LOW
            for group in buckets.values() if len(group) >= threshold
            for r in group}
