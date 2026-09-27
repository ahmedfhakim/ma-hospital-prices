"""
Find a hospital's price file through its cms-hpt.txt index.

Since 2025, CMS requires every hospital website to host https://<domain>/cms-hpt.txt,
a plain-text index with one block per hospital location:

    location-name: Example General Hospital
    source-page-url: https://example.org/price-transparency
    mrf-url: https://example.org/files/123456789_example-general_standardcharges.csv
    contact-name: Jane Doe
    contact-email: pricing@example.org

Health systems list every hospital they own in one file, so we match on location-name.
"""
from __future__ import annotations

from .http import make_session


def fetch_index(domain: str, timeout: int = 30, legacy_tls: bool = False) -> list[dict]:
    """Download and parse https://<domain>/cms-hpt.txt into a list of entries."""
    url = f"https://{domain.strip('/')}/cms-hpt.txt"
    resp = make_session(legacy_tls).get(url, timeout=timeout)
    resp.raise_for_status()
    return parse_index(resp.text)


def parse_index(text: str) -> list[dict]:
    entries, current = [], {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        # a new location-name starts a new block even without a blank line between
        if key == "location-name" and "location-name" in current:
            entries.append(current)
            current = {}
        current[key] = value.strip()
    if current:
        entries.append(current)
    return entries


def find_mrf_url(domain: str, location_match: str, legacy_tls: bool = False) -> tuple[str, dict]:
    """Return the mrf-url whose location-name contains `location_match` (case-insensitive)."""
    entries = fetch_index(domain, legacy_tls=legacy_tls)
    matches = [e for e in entries if location_match.lower() in e.get("location-name", "").lower()]
    if not matches:
        names = "\n  ".join(e.get("location-name", "?") for e in entries)
        raise LookupError(
            f"No location matching '{location_match}' in {domain}/cms-hpt.txt. Locations listed:\n  {names}"
        )
    return matches[0]["mrf-url"], matches[0]
