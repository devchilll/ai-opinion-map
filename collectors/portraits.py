"""Portraits from Wikimedia Commons, with licence and attribution recorded.

Scraping press photos is the most likely takedown this project would actually
receive. Wikimedia Commons images carry explicit licences, so we take the image
only when the API reports one, and we store the licence and the author so the UI
can attribute it. No licence, no portrait -- the initials avatar is the fallback
and it looks fine.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import yaml
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "public" / "portraits"
CREDITS = ROOT / "data" / "registry" / "portrait_credits.json"
API = "https://en.wikipedia.org/w/api.php"
from collectors.base import USER_AGENT as UA

ACCEPTABLE = ("cc by", "cc-by", "cc0", "cc zero", "public domain", "pd-", "attribution")


def lead_image(client: httpx.Client, title: str) -> tuple[str, dict] | None:
    r = client.get(API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "titles": title, "prop": "pageimages", "piprop": "original",
    })
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
    if not pages or "original" not in (pages[0] or {}):
        return None
    src = pages[0]["original"]["source"]
    # The upload URL percent-encodes the filename; Commons wants it decoded, and
    # silently returns no metadata (not an error) if it is left encoded.
    filename = "File:" + unquote(src.split("?")[0].rsplit("/", 1)[-1])

    m = client.get("https://commons.wikimedia.org/w/api.php", params={
        "action": "query", "format": "json", "formatversion": "2",
        "titles": filename, "prop": "imageinfo", "iiprop": "extmetadata|url",
    })
    m.raise_for_status()
    mp = m.json().get("query", {}).get("pages", [])
    meta = {}
    if mp and mp[0].get("imageinfo"):
        ext = mp[0]["imageinfo"][0].get("extmetadata", {})
        meta = {
            "license": (ext.get("LicenseShortName", {}) or {}).get("value", ""),
            "license_url": (ext.get("LicenseUrl", {}) or {}).get("value", ""),
            "artist": (ext.get("Artist", {}) or {}).get("value", ""),
            "credit": (ext.get("Credit", {}) or {}).get("value", ""),
            "file_page": f"https://commons.wikimedia.org/wiki/{filename.replace(' ', '_')}",
        }
    return src, meta


def acceptable(meta: dict) -> bool:
    """CC BY / CC BY-SA / CC0 / public domain are fine with attribution.
    Non-commercial and no-derivatives licences are not, so they are refused."""
    lic = (meta.get("license") or "").lower()
    if not lic or any(bad in lic for bad in ("nc", "nd", "fair use", "non-free")):
        return False
    return any(tok in lic for tok in ACCEPTABLE)


def main() -> int:
    reg = yaml.safe_load((ROOT / "data" / "registry" / "people.yaml").read_text())
    people = [p for p in reg["people"] if p.get("entity_kind", "person") != "public"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    credits = json.loads(CREDITS.read_text()) if CREDITS.exists() else {}

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for p in people:
            pid, name = p["person_id"], p["display_name"]
            dest = OUT_DIR / f"{pid}.jpg"
            if dest.exists():
                print(f"  = {pid} (have)")
                continue
            try:
                found = lead_image(client, name)
            except Exception as exc:
                print(f"  ! {pid}: {type(exc).__name__}")
                continue
            if not found:
                print(f"  - {pid}: no lead image")
                continue
            src, meta = found
            if not acceptable(meta):
                print(f"  x {pid}: licence not usable ({meta.get('license') or 'unknown'})")
                continue
            # Wikimedia rate-limits bursts; one slow retry clears most failures.
            ok = False
            for attempt in range(3):
                try:
                    img = client.get(src)
                    img.raise_for_status()
                    dest.write_bytes(img.content)
                    ok = True
                    break
                except Exception as exc:
                    if attempt == 2:
                        print(f"  ! {pid}: download failed {type(exc).__name__} {exc}"[:110])
                    time.sleep(1.5 * (attempt + 1))
            if not ok:
                continue
            time.sleep(0.4)
            credits[pid] = {"source": src, **meta}
            print(f"  + {pid}: {meta.get('license')}")

    CREDITS.write_text(json.dumps(credits, indent=1, sort_keys=True))
    print(f"\n{len(credits)} licensed portraits; credits -> {CREDITS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
