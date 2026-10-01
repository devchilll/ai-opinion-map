"""Fetch the open datasets behind the foundation-model track.

Epoch AI publishes its benchmarking hub and its notable-models table as bulk
downloads under CC BY 4.0. Bulk files are the polite way to take this data: one
request each, no page scraping. Raw files land in data/raw/models/ untouched;
pipeline/models_build.py turns them into the JSON the site reads.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.base import ROOT, USER_AGENT  # noqa: E402

OUT = ROOT / "data" / "raw" / "models"
SOURCES = {
    "benchmark_data.zip": "https://epoch.ai/data/benchmark_data.zip",
    "notable_ai_models.csv": "https://epoch.ai/data/notable_ai_models.csv",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {}}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120) as c:
        for name, url in SOURCES.items():
            r = c.get(url)
            r.raise_for_status()
            (OUT / name).write_bytes(r.content)
            manifest["files"][name] = {"url": url, "bytes": len(r.content)}
            print(f"{name}: {len(r.content):,} bytes")
            if name.endswith(".zip"):
                zipfile.ZipFile(io.BytesIO(r.content)).extractall(OUT / "bench")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
