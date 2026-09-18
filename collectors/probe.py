"""Probe seed URLs before building anything on them.

Run this first. It answers one question per seed: can this pipeline legitimately
fetch it? Nothing is parsed, nothing is scored, nothing enters the database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import Fetcher  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cfg = yaml.safe_load((ROOT / "data" / "registry" / "sources.yaml").read_text())
    fetcher = Fetcher()
    rows = []
    try:
        for person_id, spec in cfg["sources"].items():
            for seed in spec["seeds"]:
                res = fetcher.fetch(seed["url"])
                size = len(res.raw_bytes) if res.ok else 0
                rows.append((person_id, seed["url"], res.status, res.ok, size, res.error))
    finally:
        fetcher.close()

    width = max(len(r[1]) for r in rows) + 2
    print(f"{'person':<18}{'url':<{width}}{'status':<9}{'bytes':>9}  note")
    print("-" * (18 + width + 9 + 9 + 8))
    for person_id, url, status, ok, size, err in rows:
        mark = "ok" if ok else "FAIL"
        print(f"{person_id:<18}{url:<{width}}{str(status or '-'):<9}{size:>9}  {mark} {err}")

    failures = [r for r in rows if not r[3]]
    print(f"\n{len(rows) - len(failures)}/{len(rows)} seeds reachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
