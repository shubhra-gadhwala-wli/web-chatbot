"""Configured OpenAI-compatible chat client.

The endpoint URL is admin/local configuration (never user supplied), the call
is non-streaming, bounded by a 60 s timeout, and the default in config.yaml
points at a local server. No vendor is hardcoded.
"""
from __future__ import annotations

import threading


class ModelUnavailable(Exception):
    code = "model_unavailable"


class ModelTimeout(Exception):
    code = "model_timeout"


class CapacityExhausted(Exception):
    code = "capacity_exhausted"


class ConcurrencyGate:
    """ADR 3: at most `limit` in-flight answers; saturation is 429."""

    def __init__(self, limit: int):
        self._sem = threading.BoundedSemaphore(limit)

    def __enter__(self):
        if not self._sem.acquire(blocking=False):
            raise CapacityExhausted()
        return self

    def __exit__(self, *exc):
        self._sem.release()
        return False


class ChatClient:
    def __init__(self, config):
        self.config = config
        gen = config.section("generation")
        self.timeout = float(gen.get("timeout_seconds", 60))
        self.gate = ConcurrencyGate(int(gen.get("max_concurrency", 2)))

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        import httpx

        url = self.config.generation_base_url.rstrip("/") + "/chat/completions"
        headers = {"content-type": "application/json"}
        if self.config.generation_api_key:
            headers["authorization"] = f"Bearer {self.config.generation_api_key}"
        payload = {
            "model": self.config.generation_model,
            "stream": False,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ModelTimeout() from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable() from exc
        if response.status_code >= 400:
            raise ModelUnavailable()
        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable() from exc
