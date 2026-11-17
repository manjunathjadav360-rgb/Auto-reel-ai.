"""Pixabay provider (free API key, no card).

Rules taken from https://pixabay.com/api/docs/ (checked 2026-11-16):
  * 100 requests / 60 s per API key; headers X-RateLimit-Limit/-Remaining/-Reset.
  * API responses must be cached for 24 hours.
  * No systematic mass downloads; no permanent hotlinking of images.
  * Show users where media comes from (see base.credits_text).
  * The video endpoint has NO orientation filter; the image endpoint does.
    Vertical video is therefore detected client-side from rendition sizes.
Re-read the docs if Pixabay changes anything; these are not guaranteed stable.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode, urlparse

from .. import safehttp
from .base import (
    MediaAsset, MediaAuthError, MediaConfigError, MediaDownloadError,
    MediaProvider, MediaProviderError, MediaRateLimitError, credits_text,
)
from .cache import JsonCache

log = logging.getLogger("autoreel.media.pixabay")

IMAGE_ENDPOINT = "https://pixabay.com/api/"
VIDEO_ENDPOINT = "https://pixabay.com/api/videos/"
CATEGORIES = {
    "backgrounds", "fashion", "nature", "science", "education", "feelings",
    "health", "people", "religion", "places", "animals", "industry",
    "computer", "food", "sports", "transportation", "travel", "buildings",
    "business", "music",
}
ORIENTATIONS = {"vertical", "prefer_vertical", "any"}
MAX_JSON_BYTES = 5_000_000


# ------------------------------------------------------------- transport ----
HttpResponse = safehttp.HttpResponse   # re-exported for tests and callers


class UrllibTransport:
    """Standard-library HTTP client that only talks to *.pixabay.com over HTTPS.

    Redirects are checked BEFORE they are followed, so the API key (sent in the
    query string, as Pixabay requires) can never be forwarded to another host.
    """

    def __init__(self, user_agent: str = "AutoReelAI/0.1", timeout: float = 30):
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self, url: str, max_bytes: int = MAX_JSON_BYTES) -> HttpResponse:
        try:
            return safehttp.fetch(url, allowed=_allowed_host, timeout=self.timeout,
                                  max_bytes=max_bytes,
                                  headers={"User-Agent": self.user_agent})
        except safehttp.UnsafeRedirect as exc:
            raise MediaDownloadError(str(exc)) from None
        except safehttp.ResponseTooLarge as exc:
            raise MediaDownloadError(str(exc)) from None
        except safehttp.NetworkError as exc:
            raise MediaProviderError(f"Network error: {exc}") from None


# ----------------------------------------------------------- rate limiter ----
class RateLimiter:
    """Client-side sliding window, kept below Pixabay's 100/60 s default."""

    def __init__(self, max_calls: int = 90, period: float = 60.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_calls, self.period = max_calls, period
        self._clock, self._sleep = clock, sleep
        self._calls: deque = deque()
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def acquire(self) -> None:
        now = self._clock()
        if now < self._blocked_until:
            self._sleep(self._blocked_until - now)
        now = self._clock()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            self._sleep(self.period - (now - self._calls[0]))
            now = self._clock()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
        self._calls.append(self._clock())


# --------------------------------------------------------- pure functions ----
def pick_rendition(candidates: list, target_w: int = 1080, target_h: int = 1920,
                   max_bytes: Optional[int] = None) -> Optional[dict]:
    """Choose the smallest rendition that fills the target WITHOUT upscaling.

    candidates: [{"name","url","width","height","size","thumbnail"}, ...]
    If none avoids upscaling, choose the one needing the least upscaling.
    max_bytes drops oversized files first (when at least one fits).
    """
    cands = [c for c in candidates if c.get("url") and c.get("width") and c.get("height")]
    if not cands:
        return None
    if max_bytes:
        fits = [c for c in cands if not c.get("size") or c["size"] <= max_bytes]
        cands = fits or cands

    def scale(c):  # scale factor needed to COVER the target frame
        return max(target_w / c["width"], target_h / c["height"])

    no_upscale = [c for c in cands if scale(c) <= 1.0]
    if no_upscale:
        return min(no_upscale, key=lambda c: (c.get("size") or float("inf"), -c["width"]))
    return min(cands, key=scale)


def _magic_ok(kind: str, data: bytes) -> Optional[str]:
    """Return a file extension if the bytes look like the expected type."""
    if kind == "video":
        return ".mp4" if data[4:8] == b"ftyp" else None
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _allowed_host(url: str) -> bool:
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "pixabay.com" or host.endswith(".pixabay.com"))


# --------------------------------------------------------------- provider ----
class PixabayProvider(MediaProvider):
    name = "pixabay"
    display_name = "Pixabay"
    home_url = "https://pixabay.com"
    license_name = "Pixabay Content License"
    license_url = "https://pixabay.com/service/license-summary/"

    def __init__(self, api_key: str, cache_dir, *, transport=None,
                 limiter: Optional[RateLimiter] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 max_downloads: int = 15,
                 max_video_bytes: int = 80_000_000,
                 max_retries: int = 3,
                 max_rate_limit_wait: float = 65.0):
        if not api_key:
            raise MediaConfigError("PIXABAY_API_KEY is not set.")
        self._key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache = JsonCache(self.cache_dir / "pixabay_api", ttl_seconds=86400, clock=clock)
        self.transport = transport or UrllibTransport()
        self._sleep = sleep
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self.max_downloads = max_downloads
        self.max_video_bytes = max_video_bytes
        self.max_retries = max_retries
        self.max_rate_limit_wait = max_rate_limit_wait
        self.downloads_used = 0

    # -- construction ------------------------------------------------------
    @classmethod
    def from_env(cls, env=None, cache_dir="cache") -> "PixabayProvider":
        env = os.environ if env is None else env
        key = (env.get("PIXABAY_API_KEY") or "").strip()
        if not key:
            raise MediaConfigError(
                "PIXABAY_API_KEY is not set. Add it as a GitHub Actions secret "
                "(Settings > Secrets and variables > Actions)."
            )
        return cls(
            key, cache_dir,
            max_downloads=int(env.get("PIXABAY_MAX_DOWNLOADS", "15")),
            max_video_bytes=int(env.get("PIXABAY_MAX_VIDEO_MB", "80")) * 1_000_000,
        )

    def __repr__(self) -> str:  # never expose the key
        return "PixabayProvider(api_key=***)"

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***") if text else text

    # -- API access --------------------------------------------------------
    def _api_get(self, endpoint: str, params: dict, use_cache: bool = True) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        cache_key = endpoint + "?" + urlencode(sorted(params.items()))  # no API key in key
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                log.debug("cache hit: %s", cache_key)
                return cached
        url = endpoint + "?" + urlencode({"key": self._key, **params})

        for attempt in range(1, self.max_retries + 1):
            self.limiter.acquire()
            resp = self.transport.fetch(url, max_bytes=MAX_JSON_BYTES)
            self._note_rate_headers(resp.headers)
            text = self._redact(resp.body.decode("utf-8", "replace").strip()[:300])

            if resp.status == 200:
                try:
                    data = json.loads(resp.body)
                except ValueError:
                    raise MediaProviderError("Pixabay returned invalid JSON") from None
                if use_cache:
                    self.cache.set(cache_key, data)
                return data
            if resp.status == 429:
                wait = self._reset_seconds(resp.headers)
                if attempt == self.max_retries:
                    raise MediaRateLimitError(f"Pixabay rate limit exceeded: {text}", wait)
                log.warning("Pixabay 429; waiting %.0fs (attempt %d)", wait, attempt)
                self._sleep(wait)
                continue
            if resp.status >= 500:
                if attempt == self.max_retries:
                    raise MediaProviderError(f"Pixabay server error {resp.status}: {text}")
                self._sleep(2 ** attempt)
                continue
            if resp.status in (401, 403) or (resp.status == 400 and "key" in text.lower()):
                raise MediaAuthError(f"Pixabay rejected the API key ({resp.status}): {text}")
            raise MediaProviderError(f"Pixabay request failed ({resp.status}): {text}")
        raise MediaProviderError("Pixabay request failed")  # pragma: no cover

    def _reset_seconds(self, headers: dict) -> float:
        try:
            wait = float(headers.get("x-ratelimit-reset", ""))
        except ValueError:
            wait = 60.0
        return max(1.0, min(wait, self.max_rate_limit_wait))

    def _note_rate_headers(self, headers: dict) -> None:
        try:
            remaining = int(headers.get("x-ratelimit-remaining", ""))
        except ValueError:
            return
        if remaining <= 1:
            self.limiter.block_for(self._reset_seconds(headers))

    # -- parsing -----------------------------------------------------------
    def _common(self, hit: dict) -> dict:
        user = hit.get("user", "")
        uid = hit.get("user_id", "")
        return dict(
            provider=self.name, source_name=self.display_name, source_url=self.home_url,
            license_name=self.license_name, license_url=self.license_url,
            asset_id=str(hit.get("id", "")), page_url=hit.get("pageURL", ""),
            creator=user,
            creator_url=f"https://pixabay.com/users/{user}-{uid}/" if user and uid else "",
            tags=[t.strip() for t in str(hit.get("tags", "")).split(",") if t.strip()],
        )

    def _video_from_hit(self, hit: dict, target) -> Optional[MediaAsset]:
        renditions = []
        for name, r in (hit.get("videos") or {}).items():
            if isinstance(r, dict):
                renditions.append({"name": name, **r})
        best = pick_rendition(renditions, target[0], target[1], self.max_video_bytes)
        if not best or not _allowed_host(best["url"]):
            return None
        return MediaAsset(
            kind="video", download_url=best["url"], width=int(best["width"]),
            height=int(best["height"]), duration=float(hit.get("duration") or 0),
            thumbnail_url=best.get("thumbnail", ""),
            meta={"rendition": best["name"], "size": best.get("size", 0)},
            **self._common(hit),
        )

    def _image_from_hit(self, hit: dict) -> Optional[MediaAsset]:
        iw, ih = int(hit.get("imageWidth") or 0), int(hit.get("imageHeight") or 0)
        for key, cap in (("fullHDURL", 1920), ("largeImageURL", 1280), ("webformatURL", 640)):
            url = hit.get(key)
            if url and _allowed_host(url):
                break
        else:
            return None
        if not iw or not ih:
            iw, ih = int(hit.get("webformatWidth") or 0), int(hit.get("webformatHeight") or 0)
        k = min(1.0, cap / max(iw, ih)) if iw and ih else 1.0
        return MediaAsset(
            kind="image", download_url=url, width=round(iw * k), height=round(ih * k),
            thumbnail_url=hit.get("previewURL", ""),
            meta={"url_field": key, "approx_dimensions": True},
            **self._common(hit),
        )

    # -- search ------------------------------------------------------------
    @staticmethod
    def _check_common(query, category, orientation):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if category is not None and category not in CATEGORIES:
            raise ValueError(f"unknown Pixabay category: {category!r}")
        if orientation not in ORIENTATIONS:
            raise ValueError(f"orientation must be one of {sorted(ORIENTATIONS)}")

    def search_videos(self, query: str, *, orientation: str = "prefer_vertical",
                      min_duration: float = 0, max_duration: Optional[float] = None,
                      limit: int = 10, category: Optional[str] = None,
                      safesearch: bool = True, order: str = "popular", lang: str = "en",
                      video_type: str = "all", page: int = 1,
                      target=(1080, 1920)) -> list:
        """Pixabay has no video orientation filter, so we over-fetch and filter."""
        self._check_common(query, category, orientation)
        data = self._api_get(VIDEO_ENDPOINT, dict(
            q=query.strip()[:100], video_type=video_type, category=category,
            safesearch=str(bool(safesearch)).lower(), order=order, lang=lang,
            page=page, per_page=min(200, max(30, limit * 5)),
        ))
        assets = []
        for hit in data.get("hits", []):
            asset = self._video_from_hit(hit, target)
            if asset is None:
                continue
            if asset.duration < min_duration:
                continue
            if max_duration and asset.duration > max_duration:
                continue
            assets.append(asset)
        if orientation == "vertical":
            assets = [a for a in assets if a.is_vertical]
        elif orientation == "prefer_vertical":
            assets = [a for a in assets if a.is_vertical] + [a for a in assets if not a.is_vertical]
        return assets[:limit]

    def search_images(self, query: str, *, orientation: str = "prefer_vertical",
                      limit: int = 10, image_type: str = "photo",
                      category: Optional[str] = None, safesearch: bool = True,
                      order: str = "popular", lang: str = "en", min_width: int = 0,
                      min_height: int = 0, page: int = 1) -> list:
        self._check_common(query, category, orientation)

        def run(api_orientation: str) -> list:
            data = self._api_get(IMAGE_ENDPOINT, dict(
                q=query.strip()[:100], image_type=image_type, orientation=api_orientation,
                category=category, safesearch=str(bool(safesearch)).lower(), order=order,
                lang=lang, min_width=min_width or None, min_height=min_height or None,
                page=page, per_page=min(200, max(20, limit * 3)),
            ))
            return [a for a in (self._image_from_hit(h) for h in data.get("hits", [])) if a]

        if orientation == "any":
            return run("all")[:limit]
        found = run("vertical")
        if orientation == "prefer_vertical" and len(found) < min(limit, 3):
            seen = {a.asset_id for a in found}
            found += [a for a in run("all") if a.asset_id not in seen]
        return found[:limit]

    # -- download ----------------------------------------------------------
    def _refresh_image_url(self, asset: MediaAsset) -> Optional[str]:
        """Image URLs from search are only valid ~24h; look the image up again."""
        data = self._api_get(IMAGE_ENDPOINT, {"id": asset.asset_id}, use_cache=False)
        for hit in data.get("hits", []):
            fresh = self._image_from_hit(hit)
            if fresh:
                return fresh.download_url
        return None

    def download(self, asset: MediaAsset, dest_dir) -> MediaAsset:
        if asset.provider != self.name:
            raise MediaDownloadError(f"Asset belongs to {asset.provider}, not {self.name}")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stem = f"{self.name}_{asset.kind}_{asset.asset_id}"

        for existing in dest.glob(stem + ".*"):            # reuse: no new download
            if existing.suffix != ".json" and (dest / (stem + ".json")).exists():
                asset.local_path = str(existing)
                return asset

        if self.downloads_used >= self.max_downloads:
            raise MediaDownloadError(
                f"Download budget reached ({self.max_downloads} per run). "
                "Pixabay forbids systematic mass downloads."
            )
        if not _allowed_host(asset.download_url):
            raise MediaDownloadError("Refusing to download from a non-Pixabay host")

        cap = int(self.max_video_bytes * 1.25) if asset.kind == "video" else 25_000_000
        url = asset.download_url
        resp = self.transport.fetch(url, max_bytes=cap)
        if resp.status in (403, 404) and asset.kind == "image":
            fresh = self._refresh_image_url(asset)
            if fresh:
                url = asset.download_url = fresh
                resp = self.transport.fetch(url, max_bytes=cap)
        self.downloads_used += 1

        if resp.status == 429:
            raise MediaRateLimitError("Pixabay CDN rate limit", self._reset_seconds(resp.headers))
        if resp.status != 200:
            raise MediaDownloadError(f"Download failed with HTTP {resp.status}")
        if not _allowed_host(resp.final_url):
            raise MediaDownloadError("Download redirected to a non-Pixabay host")
        ext = _magic_ok(asset.kind, resp.body[:16])
        if not ext:
            raise MediaDownloadError("Downloaded file is not a valid " + asset.kind)

        final = dest / (stem + ext)
        tmp = final.with_suffix(final.suffix + ".part")
        tmp.write_bytes(resp.body)
        os.replace(tmp, final)
        asset.local_path = str(final)
        sidecar = {**asset.to_dict(), "credits": credits_text([asset]),
                   "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (dest / (stem + ".json")).write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        return asset
