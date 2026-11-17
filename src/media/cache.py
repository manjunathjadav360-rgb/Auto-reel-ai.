"""Tiny on-disk JSON cache with a time-to-live.

Pixabay requires API responses to be cached for 24 hours, so the default
TTL is 86400 seconds. Cache keys must never contain API keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


class JsonCache:
    def __init__(self, directory, ttl_seconds: int = 86400,
                 clock: Callable[[], float] = time.time):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self._clock = clock

    def _path(self, key: str) -> Path:
        return self.dir / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")

    def get(self, key: str) -> Any:
        path = self._path(key)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            if self._clock() - float(blob["stored_at"]) > self.ttl:
                return None
            return blob["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return None  # missing or corrupt entry == cache miss

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"stored_at": self._clock(), "value": value}, fh)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
