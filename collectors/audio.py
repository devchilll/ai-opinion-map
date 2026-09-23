"""Audio-only podcasts -> transcripts via local Whisper.

For shows that publish no transcript page (All-In, Possible, Decoder, No Priors),
the RSS enclosure is the audio file -- distributed over open RSS precisely so
clients can fetch it. We transcribe locally with faster-whisper.

Correctness caveat, enforced in the data: Whisper gives NO speaker labels, so
host and guest are mixed. These documents are written with
authored_by_subject=False and a note in license_note, so automated extraction
skips them. A human (or an agent reading in context) may still extract from
them via pipeline.ingest_claims, verifying from context that the guest is the
speaker -- which is usually obvious from first-person phrasing and the host's
questions.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml
from dateutil import parser as dateparser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import USER_AGENT, canonicalize  # noqa: E402
from collectors.blogs import save  # noqa: E402
from collectors.podcasts import is_guest  # noqa: E402
from pipeline.db import connect  # noqa: E402
from schema.models import Audience, DatePrecision, Document, SourceType  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "data" / "raw" / "audio"
COLLECTOR = "audio_whisper_v1"
MODEL = "small"          # good enough for quote extraction; "medium" if quotes look garbled


def download(url: str) -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    dest = AUDIO_DIR / f"{key}.mp3"
    if dest.exists():
        return dest
    with httpx.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                      timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 16):
                fh.write(chunk)
    return dest


def transcribe(path: Path) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), vad_filter=True, beam_size=1)
    return [{"start_s": round(s.start, 1), "end_s": round(s.end, 1), "text": s.text.strip()}
            for s in segments]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", nargs="*", default=None, help="person_ids to prioritise")
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    reg = yaml.safe_load((ROOT / "data" / "registry" / "people.yaml").read_text())
    people = [p for p in reg["people"] if p.get("entity_kind", "person") == "person"]
    if args.people:
        people = [p for p in people if p["person_id"] in set(args.people)]
    feeds = yaml.safe_load((ROOT / "data" / "registry" / "podcasts.yaml").read_text())["feeds"]

    with connect() as conn:
        have = {r[0] for r in conn.execute("SELECT canonical_url FROM documents")}
        have_dates = {(r[0], str(r[1])[:10]) for r in conn.execute(
            "SELECT person_id, publication_date FROM documents WHERE collector LIKE 'podcasts%' "
            "OR collector LIKE 'audio%'")}

    done = 0
    for show, feed_url in feeds.items():
        parsed = feedparser.parse(feed_url)
        for e in parsed.entries:
            if done >= args.limit:
                break
            title = e.get("title") or ""
            person = next((p for p in people if is_guest(title, p["display_name"])), None)
            if not person:
                continue
            audio = next((l["href"] for l in e.get("links", []) if l.get("rel") == "enclosure"), None)
            if not audio:
                continue
            key = canonicalize(audio).split("?")[0]
            if key in have:
                continue
            try:
                published = dateparser.parse(e.get("published")).date()
            except (ValueError, TypeError):
                continue
            if (person["person_id"], published.isoformat()) in have_dates:
                continue          # already have this episode as a page transcript

            print(f"  {show}: {title[:60]}")
            print(f"    downloading…", flush=True)
            path = download(audio)
            print(f"    transcribing {path.stat().st_size // (1 << 20)} MB with whisper-{MODEL}…", flush=True)
            segs = transcribe(path)
            text = "\n".join(s["text"] for s in segs)
            raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            doc = Document(
                doc_id=raw_hash, person_id=person["person_id"],
                source_url=audio, canonical_url=key,
                source_type=SourceType.PODCAST, source_tier=2, publisher=show, title=title[:300],
                authored_by_subject=False,     # mixed speakers: see module docstring
                utterance_date=published, publication_date=published,
                date_precision=DatePrecision.DAY, language="en",
                raw_path=str(path), raw_content_hash=raw_hash, text=text,
                collector=COLLECTOR, fetched_at=datetime.now(timezone.utc),
                audience=Audience.PODCAST, transcript_segments=segs,
                license_note="UNSEGMENTED transcript: host and guest mixed. Verify speaker before scoring.",
                date_source="rss", date_confidence="high",
            )
            n = save([doc])
            print(f"    + {person['person_id']}: {len(text.split())} words, {len(segs)} segments, {n} row")
            done += 1
    print(f"\n{done} episodes transcribed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
