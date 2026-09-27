"""
Command line:

  python -m ingest discover                 # print each hospital's price-file URL (no download)
  python -m ingest run                      # download changed files and parse them to Parquet
  python -m ingest run --only bmc           # just one hospital
  python -m ingest local FILE --id my_hosp  # parse a file you already downloaded by hand
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from .discover import find_mrf_url
from .download import download, load_manifest, save_manifest
from .parse import parse_file

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"


def load_hospitals(path: Path, only: str | None) -> list[dict]:
    hospitals = yaml.safe_load(path.read_text())["hospitals"]
    if only:
        hospitals = [h for h in hospitals if h["id"] == only]
        if not hospitals:
            sys.exit(f"No hospital with id '{only}' in {path}")
    return hospitals


def resolve_url(h: dict) -> str:
    """A pinned mrf_url wins; otherwise look it up in the hospital's cms-hpt.txt."""
    if h.get("mrf_url"):
        return h["mrf_url"]
    url, _entry = find_mrf_url(h["domain"], h["location_match"], legacy_tls=h.get("legacy_tls", False))
    return url


def cmd_discover(args):
    for h in load_hospitals(args.config, args.only):
        try:
            print(f"{h['id']:<12} {resolve_url(h)}")
        except Exception as e:  # keep going: one bad hospital shouldn't stop the rest
            print(f"{h['id']:<12} ERROR: {e}")


def cmd_run(args):
    manifest = load_manifest(MANIFEST)
    failures = 0
    for h in load_hospitals(args.config, args.only):
        hid = h["id"]
        t0 = time.time()
        try:
            url = resolve_url(h)
            print(f"[{hid}] {url}")
            result = download(url, DATA / "landing" / hid, manifest.get(hid),
                              legacy_tls=h.get("legacy_tls", False))
            print(f"[{hid}] download: {result['status']}")
            if result["status"] == "new" or args.force_parse:
                meta = parse_file(Path(result["path"]), hid, DATA / "parquet")
                result.update(parsed_rows=meta["row_count"], source_format=meta["source_format"],
                              schema_version=meta.get("version"))
                print(f"[{hid}] parsed {meta['row_count']:,} rows ({meta['source_format']}, v{meta.get('version')})")
            result.pop("status")
            manifest[hid] = {**result, "name": h.get("name"), "error": None}
        except Exception as e:
            failures += 1
            manifest.setdefault(hid, {})["error"] = f"{type(e).__name__}: {e}"
            print(f"[{hid}] FAILED: {e}")
        print(f"[{hid}] {time.time() - t0:.1f}s")
        save_manifest(MANIFEST, manifest)  # save after each hospital so progress survives a crash
    sys.exit(1 if failures else 0)


def cmd_local(args):
    meta = parse_file(Path(args.file), args.id, args.out)
    print(f"[{args.id}] parsed {meta['row_count']:,} rows ({meta['source_format']}, v{meta.get('version')})")


def main():
    p = argparse.ArgumentParser(prog="python -m ingest")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "run"):
        s = sub.add_parser(name)
        s.add_argument("--config", type=Path, default=ROOT / "hospitals.yml")
        s.add_argument("--only")
        if name == "run":
            s.add_argument("--force-parse", action="store_true", help="re-parse even if the file is unchanged")
    s = sub.add_parser("local")
    s.add_argument("file")
    s.add_argument("--id", required=True)
    s.add_argument("--out", type=Path, default=DATA / "parquet")
    args = p.parse_args()
    {"discover": cmd_discover, "run": cmd_run, "local": cmd_local}[args.cmd](args)


if __name__ == "__main__":
    main()
