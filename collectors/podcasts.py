"""Podcast interviews -> Documents containing ONLY the subject's own speech.

Why this collector matters more than any other: 10 of the cast had zero
first-person dated evidence, because people like Huang, Hassabis, Nadella and
Musk state their positions out loud rather than in writing.

Why podcasts rather than YouTube: podcast episodes are distributed over open RSS
precisely so clients can fetch them, and the shows worth using publish full
transcripts as ordinary public web pages. Pulling captions off YouTube with a
downloader conflicts with its terms; this does not.

The critical correctness rule: a transcript contains the host too. Attributing
an interviewer's words to the guest would be a serious misattribution, so we
segment by speaker and keep only the guest's turns.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import trafilatura
import yaml
from dateutil import parser as dateparser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import Fetcher, canonicalize  # noqa: E402
from collectors.blogs import save  # noqa: E402
from schema.models import Audience, DatePrecision, Document, SourceType  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = "podcasts_v1"
MIN_GUEST_WORDS = 400
TIMESTAMP = re.compile(r"^\(?\d{1,2}:\d{2}(?::\d{2})?\)?\s*[-–—]?\s*")


def speaker_labels(lines: list[str], *, min_turns: int = 4) -> set[str]:
    """Standalone short lines repeated many times are speaker names."""
    counts = Counter(
        l for l in lines
        if 3 < len(l) < 40 and l.count(" ") <= 3 and l[:1].isupper()
        and not l.endswith((".", "?", "!", ":")) and not TIMESTAMP.match(l)
    )
    return {name for name, n in counts.items() if n >= min_turns}


def guest_turns(text: str, guest_name: str) -> tuple[str, str | None]:
    """Return (guest's speech only, matched label)."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    labels = speaker_labels(lines)
    if not labels:
        return "", None

    surname = guest_name.split()[-1].lower()
    matched = next((l for l in labels if l.lower() == guest_name.lower()), None) \
        or next((l for l in labels if surname in l.lower()), None)
    if not matched:
        return "", None

    out: list[str] = []
    current: str | None = None
    for l in lines:
        if l in labels:
            current = l
            continue
        if current == matched and not TIMESTAMP.match(l):
            out.append(l)
    return "\n".join(out), matched


def is_guest(title: str, person_name: str) -> bool:
    """The person must be the guest, not merely mentioned.

    Surname-in-title matching produced false positives like a Civil War episode
    matching Kai-Fu Lee on "Lee", so require the full name AND a guest-position
    pattern: the name at the start, or right after an episode number.
    """
    if person_name.lower() not in title.lower():
        return False
    head = re.sub(r"^#?\d+\s*[-–—:]?\s*", "", title).strip().lower()
    return head.startswith(person_name.lower())


def collect(feeds: dict[str, str], people: list[dict], fetcher: Fetcher,
            *, limit_per_person: int = 4) -> list[Document]:
    docs: list[Document] = []
    taken: Counter = Counter()

    for show, feed_url in feeds.items():
        fr = fetcher.fetch(feed_url)
        if not fr.ok:
            print(f"  ! feed {show}: {fr.error}")
            continue
        parsed = feedparser.parse(fr.raw_bytes)
        print(f"  {show}: {len(parsed.entries)} episodes")

        for entry in parsed.entries:
            title = entry.get("title") or ""
            person = next((p for p in people if is_guest(title, p["display_name"])), None)
            if not person or taken[person["person_id"]] >= limit_per_person:
                continue
            page = next((l["href"] for l in entry.get("links", [])
                         if l.get("rel") == "alternate"), None)
            if not page:
                continue

            # Some shows put the episode notes on the main page and the full
            # transcript on a sibling URL. Try the page, then that sibling.
            speech, label, used_url, pr = "", None, page, None
            # Strip tracking params first: appending to a URL that still has a
            # query string edits the query, not the path.
            clean = canonicalize(page).split("?")[0]
            for candidate in (clean, clean.rstrip("/") + "-transcript"):
                cr = fetcher.fetch(candidate)
                if not cr.ok:
                    continue
                text = trafilatura.extract(cr.raw_bytes.decode("utf-8", "replace")) or ""
                got, lab = guest_turns(text, person["display_name"])
                if len(got.split()) >= MIN_GUEST_WORDS:
                    speech, label, used_url, pr = got, lab, candidate, cr
                    break
            if not pr:
                print(f"    - {person['person_id']}: no usable transcript ({title[:40]})")
                continue

            try:
                published = dateparser.parse(entry.get("published")).date()
            except (ValueError, TypeError):
                continue

            taken[person["person_id"]] += 1
            docs.append(Document(
                doc_id=pr.content_hash, person_id=person["person_id"],
                source_url=used_url, canonical_url=pr.canonical_url,
                source_type=SourceType.PODCAST, source_tier=2,
                publisher=show, title=title[:300],
                authored_by_subject=True,          # their own speech, segmented out
                utterance_date=published, publication_date=published,
                date_precision=DatePrecision.DAY, language="en",
                raw_path=pr.raw_path, raw_content_hash=pr.content_hash,
                text=speech, collector=COLLECTOR,
                fetched_at=datetime.now(timezone.utc), audience=Audience.PODCAST,
                # The publish date comes from the podcast feed itself, which is
                # authored by the publishing system rather than a page template.
                date_source="rss", date_confidence="high",
            ))
            print(f"    + {person['person_id']:<18}{published}  {len(speech.split()):>6} words "
                  f"as '{label}'  {title[:36]}")
    return docs


def main() -> int:
    reg = yaml.safe_load((ROOT / "data" / "registry" / "people.yaml").read_text())
    people = [p for p in reg["people"] if p.get("entity_kind", "person") == "person"]
    feeds = yaml.safe_load((ROOT / "data" / "registry" / "podcasts.yaml").read_text())["feeds"]

    fetcher = Fetcher()
    try:
        docs = collect(feeds, people, fetcher)
    finally:
        fetcher.close()
    print(f"\n{len(docs)} interview documents, {save(docs)} new rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
