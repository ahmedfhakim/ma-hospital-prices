"""
HTTP sessions for hospital websites.

Some hospital web servers still use TLS "legacy renegotiation", which OpenSSL 3
(and so modern Python) refuses by default:
    SSLError: UNSAFE_LEGACY_RENEGOTIATION_DISABLED
For those hospitals only, hospitals.yml sets `legacy_tls: true`. That allows the
old handshake for that one host while certificate verification stays ON. Every
other hospital uses the strict default.
"""
from __future__ import annotations

import ssl

import certifi
import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "ma-hospital-prices/0.1 (portfolio project; contact via GitHub)"
OP_LEGACY_SERVER_CONNECT = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)


class LegacyRenegotiationAdapter(HTTPAdapter):
    """Verified TLS (certifi CA bundle, hostname check) + legacy renegotiation allowed."""

    def _context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.options |= OP_LEGACY_SERVER_CONNECT
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().proxy_manager_for(*args, **kwargs)


def make_session(legacy_tls: bool = False) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    if legacy_tls:
        s.mount("https://", LegacyRenegotiationAdapter())
    return s
