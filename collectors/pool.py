"""Parallel fetching, sharded by host.

The concurrency contract, which matters more than the speed:

  1. ONE worker per host. Politeness is per-origin, so sharding the work by host
     lets 12 hosts run at once while no host ever sees two concurrent requests.
     Raising workers beyond that would hammer a single site, not go faster.
  2. NO shared mutable fetch state. Each worker builds its own Fetcher with its
     own connection pool and its own robots cache. Nothing is passed between
     threads except finished results over a queue.
  3. ONE writer. Workers never touch SQLite or the cache index. They return
     records; the main thread writes them. This is why two collectors running at
     once cannot interleave a half-written row.
  4. Writes are atomic and idempotent. The raw cache is content-addressed, so the
     same bytes always land at the same path and a re-run overwrites nothing.
     Document inserts are INSERT OR IGNORE on a unique canonical_url.
  5. A crashed worker loses its own host, not the run.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.parse import urlparse

from collectors.base import Fetcher, FetchResult

MAX_HOST_WORKERS = 12


@dataclass
class Job:
    url: str
    meta: dict = field(default_factory=dict)


@dataclass
class Done:
    job: Job
    result: FetchResult | None
    error: str = ""


def shard_by_host(jobs: Iterable[Job]) -> dict[str, list[Job]]:
    buckets: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        buckets[urlparse(j.url).netloc].append(j)
    return dict(buckets)


def _worker(host: str, jobs: list[Job], out: queue.Queue, stop: threading.Event,
            min_interval_s: float) -> None:
    """Owns one host end to end. Its Fetcher is private to this thread."""
    fetcher = Fetcher(min_interval_s=min_interval_s)
    try:
        for job in jobs:
            if stop.is_set():
                return
            try:
                out.put(Done(job, fetcher.fetch(job.url)))
            except Exception as exc:                      # one bad URL must not kill the host
                out.put(Done(job, None, f"{type(exc).__name__}: {exc}"))
    finally:
        fetcher.close()


def run(jobs: list[Job], *, on_result: Callable[[Done], None],
        max_workers: int = MAX_HOST_WORKERS, min_interval_s: float = 2.0,
        progress_every: float = 5.0) -> dict[str, int]:
    """Fetch every job, at most one request per host at a time.

    on_result is called on the MAIN thread only -- it is the single writer.
    """
    buckets = shard_by_host(jobs)
    out: queue.Queue[Done] = queue.Queue()
    stop = threading.Event()
    pending = list(buckets.items())
    running: list[threading.Thread] = []
    stats = {"ok": 0, "failed": 0, "total": len(jobs)}
    seen = 0
    last_report = time.monotonic()

    def top_up() -> None:
        while pending and len([t for t in running if t.is_alive()]) < max_workers:
            host, host_jobs = pending.pop(0)
            t = threading.Thread(target=_worker,
                                 args=(host, host_jobs, out, stop, min_interval_s),
                                 name=f"fetch-{host}", daemon=True)
            t.start()
            running.append(t)

    top_up()
    try:
        while seen < len(jobs):
            try:
                done = out.get(timeout=1.0)
            except queue.Empty:
                top_up()
                if not any(t.is_alive() for t in running) and not pending:
                    break
                continue

            seen += 1
            if done.result and done.result.ok:
                stats["ok"] += 1
            else:
                stats["failed"] += 1
            on_result(done)                                # single writer, main thread
            top_up()

            if time.monotonic() - last_report >= progress_every:
                alive = len([t for t in running if t.is_alive()])
                print(f"  [{seen}/{len(jobs)}] ok={stats['ok']} failed={stats['failed']} "
                      f"hosts_active={alive} hosts_queued={len(pending)}", flush=True)
                last_report = time.monotonic()
    except KeyboardInterrupt:
        stop.set()
        raise
    finally:
        stop.set()
        for t in running:
            t.join(timeout=3.0)

    return stats
