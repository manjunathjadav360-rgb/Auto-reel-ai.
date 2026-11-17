"""Standard-library HTTP helper that refuses to follow redirects to hosts we
did not approve.

Why: urllib follows redirects silently and re-sends custom headers. An
attacker-controlled (or compromised) redirect could otherwise receive an API
key that travels in a query string or header. Every URL, including each
redirect target, must pass the caller's `allowed` predicate BEFORE any request
is made to it.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse


class UnsafeRedirect(Exception):
    """A URL or redirect target was not on the allow-list."""


class NetworkError(Exception):
    """Connection, DNS or timeout problem (message contains no URL or secrets)."""


class ResponseTooLarge(Exception):
    pass


@dataclass
class HttpResponse:
    status: int
    headers: dict      # lower-cased keys
    body: bytes
    final_url: str


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "?").lower()


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, allowed: Callable[[str], bool]):
        self._allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self._allowed(newurl):
            raise UnsafeRedirect(f"Blocked redirect to host {host_of(newurl)!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_limited(resp, max_bytes: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLarge(f"Response larger than {max_bytes} bytes")
        chunks.append(chunk)


def fetch(url: str, *, allowed: Callable[[str], bool], method: str = "GET",
          headers: Optional[dict] = None, data: Optional[bytes] = None,
          timeout: float = 30, max_bytes: int = 5_000_000) -> HttpResponse:
    if not allowed(url):
        raise UnsafeRedirect(f"Blocked request to host {host_of(url)!r}")
    opener = urllib.request.build_opener(_GuardedRedirect(allowed))
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as resp:
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return HttpResponse(resp.status, hdrs, _read_limited(resp, max_bytes), resp.geturl())
    except urllib.error.HTTPError as exc:
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return HttpResponse(exc.code, hdrs, exc.read(4000), url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(exc.__cause__, UnsafeRedirect):
            raise exc.__cause__
        if isinstance(getattr(exc, "reason", None), UnsafeRedirect):
            raise exc.reason
        raise NetworkError(type(exc).__name__) from None
