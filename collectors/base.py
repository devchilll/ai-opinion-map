"""Shared fetch machinery. Every collector goes through this.

Rules enforced here, not left to each collector:
  - honest user agent
  - robots.txt respected, per host, cached
  - rate limited per host
  - one fetch per URL, ever (content-addressed cache on disk)
  - raw bytes kept verbatim and never edited
  - a failed fetch writes access_ok=False rather than a partial record
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import httpx

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CACHE_INDEX = RAW_DIR / "_index.jsonl"

# Wikimedia (and others) reject User-Agents containing "example.com" outright --
# it is named in their robot policy. A placeholder contact is not a neutral
# default: it is an actively blocked one. Set AIOM_CONTACT to a real URL or
# address before running at any scale.
CONTACT = os.environ.get("AIOM_CONTACT", "https://github.com/ai-opinion-map")
USER_AGENT = (
    f"ai-opinion-map/0.1 ({CONTACT}; research project mapping public "
    f"statements about AI) httpx"
)
MIN_INTERVAL_S = 2.0          # per host
TIMEOUT_S = 30.0

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "ref_url")


@dataclass
class FetchResult:
    url: str
    canonical_url: str
    ok: bool
    status: int | None
    raw_path: str | None
    content_hash: str | None
    content_type: str
    fetched_at: datetime
    error: str = ""

    @property
    def raw_bytes(self) -> bytes:
        if not self.raw_path:
            return b""
        return Path(self.raw_path).read_bytes()


def canonicalize(url: str) -> str:
    """Strip tracking params and fragments so the same page hashes to one entry."""
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(_TRACKING_PREFIXES)]
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", urlencode(q), ""))


class Fetcher:
    def __init__(self, *, respect_robots: bool = True, min_interval_s: float = MIN_INTERVAL_S):
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._respect_robots = respect_robots
        self._min_interval = min_interval_s
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=TIMEOUT_S,
        )
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self._seen = self._load_index()

    def _load_index(self) -> dict[str, dict]:
        if not CACHE_INDEX.exists():
            return {}
        seen = {}
        for line in CACHE_INDEX.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                seen[rec["canonical_url"]] = rec
        return seen

    def _robots_allows(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
            try:
                r = self._client.get(robots_url)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None          # no robots.txt served -> allowed
            except Exception:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_hit.get(host, 0.0)
        wait = self._min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def fetch(self, url: str, *, force: bool = False) -> FetchResult:
        canonical = canonicalize(url)
        now = datetime.now(timezone.utc)

        if not force and canonical in self._seen:
            rec = self._seen[canonical]
            return FetchResult(
                url=url, canonical_url=canonical, ok=rec["ok"], status=rec.get("status"),
                raw_path=rec.get("raw_path"), content_hash=rec.get("content_hash"),
                content_type=rec.get("content_type", ""), fetched_at=now, error="cached",
            )

        if not self._robots_allows(canonical):
            return self._record(FetchResult(
                url=url, canonical_url=canonical, ok=False, status=None, raw_path=None,
                content_hash=None, content_type="", fetched_at=now,
                error="blocked by robots.txt",
            ))

        self._throttle(canonical)
        try:
            r = self._client.get(canonical)
        except Exception as exc:
            return self._record(FetchResult(
                url=url, canonical_url=canonical, ok=False, status=None, raw_path=None,
                content_hash=None, content_type="", fetched_at=now, error=f"{type(exc).__name__}: {exc}",
            ))

        if r.status_code != 200:
            return self._record(FetchResult(
                url=url, canonical_url=canonical, ok=False, status=r.status_code, raw_path=None,
                content_hash=None, content_type=r.headers.get("content-type", ""),
                fetched_at=now, error=f"HTTP {r.status_code}",
            ))

        digest = hashlib.sha256(r.content).hexdigest()
        path = RAW_DIR / digest[:2] / f"{digest}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(r.content)

        return self._record(FetchResult(
            url=url, canonical_url=canonical, ok=True, status=200, raw_path=str(path),
            content_hash=digest, content_type=r.headers.get("content-type", ""), fetched_at=now,
        ))

    def _record(self, res: FetchResult) -> FetchResult:
        with CACHE_INDEX.open("a") as fh:
            fh.write(json.dumps({
                "canonical_url": res.canonical_url, "ok": res.ok, "status": res.status,
                "raw_path": res.raw_path, "content_hash": res.content_hash,
                "content_type": res.content_type, "fetched_at": res.fetched_at.isoformat(),
                "error": res.error,
            }) + "\n")
        self._seen[res.canonical_url] = {
            "canonical_url": res.canonical_url, "ok": res.ok, "status": res.status,
            "raw_path": res.raw_path, "content_hash": res.content_hash,
            "content_type": res.content_type,
        }
        return res

    def close(self) -> None:
        self._client.close()


# --- concurrency note -------------------------------------------------------
# Fetcher is deliberately NOT thread-safe and is never shared. collectors/pool.py
# gives each worker thread its own instance. The only cross-thread state is the
# append-only cache index on disk, and appends of a single short line under
# O_APPEND do not interleave. Workers still keep their own in-memory view, so a
# URL can be fetched twice across a run's start -- content addressing makes that
# harmless: identical bytes hash to the same path and overwrite nothing.
