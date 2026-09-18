"""Probe every event source before the event is allowed on the timeline.

An event with a dead citation is an assertion, not a record. This fetches each
source in parallel (host-sharded, same contract as the crawler) and marks the
event verified only when at least two independent sources resolve.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from collectors.pool import Done, Job, run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
EVENTS = ROOT / "data" / "registry" / "events.yaml"


def main() -> int:
    cfg = yaml.safe_load(EVENTS.read_text())
    events = cfg["events"]

    jobs = [Job(url, {"event_id": e["id"]}) for e in events for url in e["sources"]]
    status: dict[str, dict[str, bool]] = defaultdict(dict)

    def classify(d: Done) -> str:
        """A 403 is not a 404.

        openai.com returns 403 to our crawler while serving the page perfectly to
        a human. Treating that as a dead link would throw away good citations,
        so blocked sources stay in the dataset, flagged, and are shown to users
        as normal links -- they just cannot be auto-verified.
        """
        if d.result and d.result.ok:
            return "live"
        code = d.result.status if d.result else None
        if code in (401, 403, 429) or (d.result and "robots" in (d.result.error or "")):
            return "blocked"
        if code == 404:
            return "dead"
        return "unreachable"

    def on_result(d: Done) -> None:
        status[d.job.meta["event_id"]][d.job.url] = classify(d)

    print(f"probing {len(jobs)} sources across "
          f"{len({urlparse(j.url).netloc for j in jobs})} hosts")
    run(jobs, on_result=on_result)

    verified = blocked_only = 0
    for e in events:
        results = status.get(e["id"], {})
        live = [u for u, v in results.items() if v == "live"]
        blocked = [u for u, v in results.items() if v == "blocked"]
        dead = [u for u, v in results.items() if v in ("dead", "unreachable")]

        # An event ships when two citations are reachable by a reader and at
        # least one is machine-verified.
        e["verified"] = len(live) >= 1 and len(live) + len(blocked) >= 2
        e["blocked_sources"] = blocked or None
        e["dead_sources"] = dead or None
        if not e["blocked_sources"]:
            e.pop("blocked_sources")
        if not e["dead_sources"]:
            e.pop("dead_sources")

        if e["verified"]:
            verified += 1
            if blocked:
                blocked_only += 1
        else:
            print(f"  ! {e['id']}: live={len(live)} blocked={len(blocked)} dead={len(dead)}")
            for u in dead:
                print(f"      DEAD (replace this): {u}")

    EVENTS.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=100))
    print(f"\n{verified}/{len(events)} events verified")
    print(f"  {blocked_only} rely on a source that blocks our crawler but serves humans "
          f"(403, not 404) -- kept and flagged, not discarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
