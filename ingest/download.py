"""
Download a price file, streaming to disk, and skip work when nothing changed.

Change detection is two-level:
  1. The server's ETag / Last-Modified matches what we saw last time -> skip the download.
  2. Otherwise download, then compare the SHA-256 of the content -> skip re-parsing if identical.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .http import make_session

CHUNK = 1024 * 1024  # 1 MB


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest_dir: Path, previous: dict | None = None, timeout: int = 60,
             legacy_tls: bool = False) -> dict:
    """
    Returns a dict describing the result:
      status: "unchanged_remote" | "unchanged_content" | "new"
      path, sha256, etag, last_modified, downloaded_at
    """
    previous = previous or {}
    session = make_session(legacy_tls)

    # 1. Cheap check: has the server's version marker changed?
    try:
        head = session.head(url, timeout=timeout, allow_redirects=True)
        etag, last_mod = head.headers.get("ETag"), head.headers.get("Last-Modified")
        if previous.get("path") and Path(previous["path"]).exists() and (
            (etag and etag == previous.get("etag"))
            or (last_mod and last_mod == previous.get("last_modified"))
        ):
            return {**previous, "status": "unchanged_remote"}
    except requests.RequestException:
        etag = last_mod = None  # some hospital servers reject HEAD; just download

    # 2. Stream the file to disk while hashing it
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(unquote(urlparse(url).path)).name or "mrf"
    tmp = dest_dir / f".{filename}.part"
    h = hashlib.sha256()
    with session.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        etag = etag or r.headers.get("ETag")
        last_mod = last_mod or r.headers.get("Last-Modified")
        with open(tmp, "wb") as f:
            for block in r.iter_content(CHUNK):
                f.write(block)
                h.update(block)
    digest = h.hexdigest()

    result = {
        "url": url,
        "sha256": digest,
        "etag": etag,
        "last_modified": last_mod,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if digest == previous.get("sha256") and previous.get("path") and Path(previous["path"]).exists():
        tmp.unlink()
        return {**previous, **result, "status": "unchanged_content"}

    final = dest_dir / filename
    tmp.replace(final)
    final = unzip_if_needed(final)
    return {**result, "path": str(final), "status": "new"}


def unzip_if_needed(path: Path) -> Path:
    """Some hospitals publish a .zip. Extract the largest CSV/JSON inside it."""
    if not zipfile.is_zipfile(path):
        return path
    with zipfile.ZipFile(path) as z:
        members = [m for m in z.infolist() if m.filename.lower().endswith((".csv", ".json"))]
        if not members:
            raise ValueError(f"{path.name} is a zip with no CSV or JSON inside")
        biggest = max(members, key=lambda m: m.file_size)
        out = path.parent / Path(biggest.filename).name
        with z.open(biggest) as src, open(out, "wb") as dst:
            for block in iter(lambda: src.read(CHUNK), b""):
                dst.write(block)
    path.unlink()
    return out
