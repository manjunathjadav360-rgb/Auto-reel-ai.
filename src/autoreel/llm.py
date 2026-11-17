"""Gemini REST client (free tier via an AI Studio key; no SDK dependency).

The API key is sent in the x-goog-api-key header, never in the URL, and every
URL (and redirect) must be on generativelanguage.googleapis.com over HTTPS.
Free-tier limits are per project, change over time, and are not guaranteed:
the client retries 429s with the server's suggested delay, then falls back to
the next model in GEMINI_MODELS.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from .. import safehttp

log = logging.getLogger("autoreel.llm")
HOST = "generativelanguage.googleapis.com"
BASE = f"https://{HOST}/v1beta/models/"


class GeminiError(Exception):
    pass


class GeminiAuthError(GeminiError):
    pass


def _allowed(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and (p.hostname or "").lower() == HOST


def default_transport(url: str, headers: dict, body: bytes) -> safehttp.HttpResponse:
    return safehttp.fetch(url, allowed=_allowed, method="POST", headers=headers,
                          data=body, timeout=90, max_bytes=4_000_000)


def _retry_delay(resp: safehttp.HttpResponse) -> Optional[float]:
    try:
        for d in json.loads(resp.body).get("error", {}).get("details", []):
            m = re.match(r"^([\d.]+)s$", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    except (ValueError, AttributeError):
        pass
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


def _error_text(resp, key: str) -> str:
    text = resp.body.decode("utf-8", "replace")
    try:
        text = json.loads(text).get("error", {}).get("message", text)
    except ValueError:
        pass
    return text.replace(key, "***")[:240]


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


class GeminiClient:
    def __init__(self, api_key: str, models=("gemini-3.8-flash", "gemini-3.5-flash-lite"), *,
                 transport: Callable = default_transport, sleep: Callable = time.sleep,
                 max_attempts: int = 3, max_wait: float = 60.0):
        if not api_key:
            raise GeminiAuthError("GEMINI_API_KEY is not set (add it as a GitHub secret).")
        self._key = api_key
        self.models = list(models)
        self._transport, self._sleep = transport, sleep
        self.max_attempts, self.max_wait = max_attempts, max_wait
        self.calls = 0

    def __repr__(self):
        return "GeminiClient(api_key=***)"

    def generate_json(self, prompt: str, *, system: str = None, temperature: float = 0.8,
                      max_output_tokens: int = 8192) -> Any:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_output_tokens,
                                 "responseMimeType": "application/json"},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        body = json.dumps(payload).encode("utf-8")
        failures = []
        for model in self.models:
            try:
                return self._try_model(model, body)
            except GeminiAuthError:
                raise
            except GeminiError as exc:
                failures.append(f"{model}: {exc}")
                log.warning("Gemini model %s failed: %s", model, exc)
        raise GeminiError("All Gemini models failed. " + " || ".join(failures))

    def _try_model(self, model: str, body: bytes) -> Any:
        url = f"{BASE}{model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        last = "no attempt"
        for attempt in range(1, self.max_attempts + 1):
            self.calls += 1
            try:
                resp = self._transport(url, headers, body)
            except safehttp.UnsafeRedirect as exc:
                raise GeminiError(str(exc)) from None
            except safehttp.NetworkError as exc:
                last = f"network error ({exc})"
                self._sleep(2 ** attempt)
                continue
            if resp.status == 200:
                try:
                    return self._parse(resp)
                except GeminiError as exc:
                    last = str(exc)
                    continue
            text = _error_text(resp, self._key)
            if resp.status in (401, 403) or (resp.status == 400 and "api key" in text.lower()):
                raise GeminiAuthError(f"Gemini rejected the API key/project ({resp.status}): {text}")
            if resp.status == 404:
                raise GeminiError(f"model not available ({text})")
            if resp.status == 429:
                wait = _retry_delay(resp) or 20.0
                if wait > self.max_wait:
                    raise GeminiError(f"quota exhausted (retry in {wait:.0f}s)")
                last = f"rate limited, waiting {wait:.0f}s"
                log.warning("Gemini 429 on %s; waiting %.0fs", model, wait)
                self._sleep(wait)
                continue
            if resp.status >= 500:
                last = f"server error {resp.status}"
                self._sleep(2 ** attempt)
                continue
            raise GeminiError(f"request failed ({resp.status}): {text}")
        raise GeminiError(f"gave up after {self.max_attempts} attempts ({last})")

    @staticmethod
    def _parse(resp) -> Any:
        try:
            data = json.loads(resp.body)
        except ValueError:
            raise GeminiError("invalid JSON from API") from None
        if data.get("promptFeedback", {}).get("blockReason"):
            raise GeminiError("prompt blocked: " + str(data["promptFeedback"]["blockReason"]))
        cands = data.get("candidates") or []
        if not cands:
            raise GeminiError("no candidates returned")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            raise GeminiError("empty response (finishReason=%s)" % cands[0].get("finishReason"))
        try:
            return _extract_json(text)
        except ValueError:
            raise GeminiError("model did not return valid JSON") from None
