"""Provider registry and fallback chain.

The rest of AUTO REEL AI talks only to MediaManager. To add a provider:
write a MediaProvider subclass, add it to PROVIDER_CLASSES, and list its
name in the MEDIA_PROVIDERS environment variable.
"""
from __future__ import annotations

import logging
import os

from .base import (
    MediaAuthError, MediaConfigError, MediaError, MediaProviderError,
    MediaRateLimitError, credits_text,
)
from .pixabay import PixabayProvider

log = logging.getLogger("autoreel.media")

PROVIDER_CLASSES = {"pixabay": PixabayProvider}


class MediaManager:
    def __init__(self, providers):
        if not providers:
            raise MediaConfigError("No media providers are configured.")
        self.providers = list(providers)
        self.by_name = {p.name: p for p in self.providers}
        self.issues = []          # surfaced in the quality/production report

    def _search(self, method: str, query: str, **options) -> list:
        for provider in self.providers:
            try:
                found = getattr(provider, method)(query, **options)
            except (MediaRateLimitError, MediaAuthError, MediaProviderError) as exc:
                self.issues.append({"provider": provider.name, "query": query,
                                    "error": type(exc).__name__, "detail": str(exc)})
                log.warning("%s failed for %r: %s", provider.name, query, exc)
                continue
            if found:
                return found
        return []   # caller falls back to typography/animated-still scenes

    def search_videos(self, query: str, **options) -> list:
        return self._search("search_videos", query, **options)

    def search_images(self, query: str, **options) -> list:
        return self._search("search_images", query, **options)

    def download(self, asset, dest_dir):
        provider = self.by_name.get(asset.provider)
        if provider is None:
            raise MediaError(f"Provider {asset.provider!r} is not configured")
        return provider.download(asset, dest_dir)

    def source_notice(self) -> str:
        """Text the dashboard must show next to any media search results."""
        return "Media sources: " + ", ".join(
            f"{p.display_name} ({p.home_url})" for p in self.providers)

    @staticmethod
    def credits(assets) -> str:
        return credits_text(assets)


def build_manager_from_env(env=None, cache_dir="cache") -> MediaManager:
    env = os.environ if env is None else env
    names = [n.strip().lower() for n in env.get("MEDIA_PROVIDERS", "pixabay").split(",") if n.strip()]
    providers = []
    for name in names:
        cls = PROVIDER_CLASSES.get(name)
        if cls is None:
            raise MediaConfigError(f"Unknown media provider: {name!r}")
        try:
            providers.append(cls.from_env(env, cache_dir))
        except MediaConfigError as exc:
            log.warning("Skipping provider %s: %s", name, exc)
    return MediaManager(providers)
