"""Epoch AI bulk files -> data/out/models.json, the model track's only input.

Nothing here is estimated or filled in. A point exists because a named model
got a recorded score on a named benchmark; the frontier is the running best of
those points. Scores are kept raw (0-1) and also rescaled between the
benchmark's chance baseline and its ceiling, so "how much of this benchmark is
left" is comparable across benchmarks.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "models"
BENCH = RAW / "bench"
OUT = ROOT / "data" / "out" / "models.json"
START = "2017-01-01"

csv.field_size_limit(sys.maxsize)
_EFFORT = re.compile(r"_(max|xhigh|high|medium|low|minimal|none|unknown|\d+k?)$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


class Labs:
    def __init__(self, spec: list[dict]):
        self.order = [l["id"] for l in spec]
        self.names = {l["id"]: l["name"] for l in spec}
        self._match = {m.lower(): l["id"] for l in spec for m in l["match"]}

    def of(self, org: str) -> str:
        """A model belongs to the first listed organisation that is a tracked lab."""
        for part in (org or "").split(","):
            hit = self._match.get(part.strip().lower())
            if hit:
                return hit
        return "other"


def model_names() -> dict[str, dict]:
    out = {}
    for r in rows(BENCH / "model_metadata.csv"):
        if r.get("model_version"):
            out[r["model_version"]] = r
    return out


def display(version: str, row: dict, meta: dict[str, dict]) -> str:
    m = meta.get(version)
    if m and (m.get("model_group") or m.get("display_name")):
        return m.get("model_group") or m["display_name"]
    return _EFFORT.sub("", version)


def is_open(access: str) -> bool | None:
    a = (access or "").lower()
    if not a:
        return None
    return a.startswith("open weights")


def benchmark(spec: dict, bmeta: dict[str, dict], meta: dict[str, dict], labs: Labs) -> dict | None:
    m = bmeta.get(spec["name"], {})
    fname = spec.get("file") or m.get("source_file")
    col = spec.get("column") or m.get("score_column")
    if not fname or not (BENCH / fname).exists():
        print(f"  skip {spec['name']}: no data file", file=sys.stderr)
        return None
    data = rows(BENCH / fname)
    scale = num(m.get("scale")) or 1.0
    vals = [num(r.get(col)) for r in data]
    if "file" in spec and max((v for v in vals if v is not None), default=0) > 1.5:
        scale = 0.01
    baseline = spec.get("baseline", num(m.get("random_baseline")) or 0.0)
    ceiling = num(m.get("score_ceiling")) or 1.0

    best: dict[str, dict] = {}
    for r, v in zip(data, vals):
        d = r.get("Release date", "")
        if v is None or not _DATE.match(d) or d < START:
            continue
        raw = v * scale
        name = display(r["Model version"], r, meta)
        mm = meta.get(r["Model version"], {})
        pt = {
            "m": name,
            "lab": labs.of(r.get("Organization", "")),
            "org": (r.get("Organization") or "").split(",")[0].strip(),
            "d": d,
            "s": round(raw, 4),
            "n": round(max(0.0, min(1.0, (raw - baseline) / (ceiling - baseline))), 4),
            "open": is_open(mm.get("accessibility", "")),
        }
        if name not in best or pt["s"] > best[name]["s"]:
            best[name] = pt
    pts = sorted(best.values(), key=lambda p: (p["d"], p["s"]))
    if len(pts) < 3:
        return None
    top, frontier = -1.0, []
    for p in pts:
        if p["s"] > top:
            top = p["s"]
            frontier.append(p)
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", spec["name"].lower()).strip("-"),
        "name": spec.get("label", spec["name"]),
        "gloss": spec["gloss"],
        "released": m.get("release_date") or None,
        "baseline": baseline,
        "ceiling": ceiling,
        "points": pts,
        "frontier": frontier,
    }


def build() -> dict:
    reg = yaml.safe_load((ROOT / "data" / "registry" / "benchmarks.yaml").read_text())
    labs = Labs(reg["labs"])
    meta = model_names()
    bmeta = {r["benchmark"]: r for r in rows(BENCH / "benchmark_metadata.csv")}

    directions = []
    for d in reg["directions"]:
        bs = [b for b in (benchmark(s, bmeta, meta, labs) for s in d["benchmarks"]) if b]
        directions.append({"id": d["id"], "label": d["label"], "blurb": d["blurb"], "benchmarks": bs})

    eci = []
    for r in rows(BENCH / "epoch_capabilities_index" / "eci_scores.csv"):
        v = num(r["eci"])
        if v is None or not _DATE.match(r["date"]):
            continue
        eci.append({
            "m": r["Display name"] or r["Model"],
            "lab": labs.of(r["Organization"]),
            "org": r["Organization"].split(",")[0].strip(),
            "country": r["Country (of organization)"],
            "d": r["date"],
            "v": v, "lo": num(r["eci_ci_low"]), "hi": num(r["eci_ci_high"]),
            "open": r["Accessibility group"] == "Open weights",
        })
    eci.sort(key=lambda p: p["d"])

    horizon = {}
    for r in rows(BENCH / "metr_time_horizons_external.csv"):
        v = num(r["Time horizon"])
        d = r["Release date"]
        if v is None or not _DATE.match(d) or d < START:
            continue
        name = display(r["Model version"], r, meta)
        pt = {"m": name, "lab": labs.of(r["Organization"]), "org": r["Organization"].split(",")[0].strip(),
              "d": d, "min": round(v, 3), "lo": num(r["CI_low"]), "hi": num(r["CI_high"])}
        if name not in horizon or pt["min"] > horizon[name]["min"]:
            horizon[name] = pt
    horizon = sorted(horizon.values(), key=lambda p: p["d"])

    releases = []
    for r in rows(RAW / "notable_ai_models.csv"):
        d = r["Publication date"]
        if not _DATE.match(d) or d < START:
            continue
        releases.append({
            "m": r["Model"],
            "lab": labs.of(r["Organization"]),
            "org": r["Organization"].split(",")[0].strip(),
            "d": d,
            "domains": [x.strip() for x in r["Domain"].split(",") if x.strip()],
            "params": num(r["Parameters"]),
            "compute": num(r["Training compute (FLOP)"]),
            "open": is_open(r.get("Model accessibility", "")),
            "frontier": r.get("Frontier model", "").strip().lower() in ("true", "yes", "checked", "1"),
            "link": r["Link"] if r["Link"].startswith("http") else None,
        })
    releases.sort(key=lambda p: p["d"])

    # One entry per (organisation, day): a lab shipping four sizes of one
    # model on one day made one release, not four.
    FOUNDATION = {"Language", "Multimodal", "Vision", "Image generation", "Video", "Speech", "Audio"}
    days: dict[tuple[str, str], dict] = {}
    for src in (
        [(p["org"], p["lab"], p["d"], p["m"]) for p in eci],
        [(r["org"], r["lab"], r["d"], r["m"]) for r in releases if FOUNDATION & set(r["domains"])],
    ):
        for org, lab, d, m in src:
            e = days.setdefault((org, d), {"lab": lab, "org": org, "d": d, "names": []})
            if m not in e["names"]:
                e["names"].append(m)
    cadence = sorted(days.values(), key=lambda e: e["d"])

    manifest = json.loads((RAW / "manifest.json").read_text()) if (RAW / "manifest.json").exists() else {}
    return {
        "generated": date.today().isoformat(),
        "source": {
            "name": "Epoch AI",
            "license": "CC BY 4.0",
            "url": "https://epoch.ai/benchmarks",
            "citation": "Epoch AI, 'Capabilities & benchmarking' and 'Notable AI Models'. Published online at epoch.ai.",
            "retrieved": manifest.get("retrieved"),
        },
        "labs": [{"id": i, "name": labs.names[i]} for i in labs.order] + [{"id": "other", "name": "Other"}],
        "directions": directions,
        "eci": eci,
        "horizon": horizon,
        "releases": releases,
        "cadence": cadence,
    }


def main() -> int:
    out = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    web = ROOT / "web" / "public" / "data" / "models.json"
    if web.parent.exists():
        web.write_text(OUT.read_text())
    n_b = sum(len(d["benchmarks"]) for d in out["directions"])
    n_p = sum(len(b["points"]) for d in out["directions"] for b in d["benchmarks"])
    print(f"{n_b} benchmarks, {n_p} scores, {len(out['eci'])} ECI, "
          f"{len(out['horizon'])} horizons, {len(out['releases'])} releases -> {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
