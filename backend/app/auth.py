"""ADR 2 identity: Argon2id hashes, opaque 256-bit session tokens, SHA-256
digest at rest, absolute 14-day expiry, rotation on login/registration,
same-origin CSRF enforcement and local rate limiting."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

SESSION_COOKIE = "session"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
# Constant-cost decoy so a login for an unknown email does the same work.
_DECOY_HASH = None


@dataclass
class Session:
    id: str
    account_id: str
    token: str | None = None


class PasswordPolicyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_email(email: str) -> str:
    email = (email or "").strip()
    if len(email) > 320 or not _EMAIL_RE.match(email):
        raise PasswordPolicyError("invalid_email")
    return email.lower()


def validate_password(password: str, min_length: int, max_bytes: int) -> str:
    if not isinstance(password, str):
        raise PasswordPolicyError("invalid_password")
    if len(password.encode("utf-8")) > max_bytes:
        raise PasswordPolicyError("password_too_long")
    if len(password) < min_length:
        raise PasswordPolicyError("password_too_short")
    return password


def hasher(config) -> PasswordHasher:
    a = config.section("auth").get("argon2", {})
    return PasswordHasher(time_cost=int(a.get("time_cost", 3)),
                          memory_cost=int(a.get("memory_cost_kib", 65536)),
                          parallelism=int(a.get("parallelism", 1)),
                          hash_len=32, salt_len=16)


def decoy_hash(config) -> str:
    global _DECOY_HASH
    if _DECOY_HASH is None:
        _DECOY_HASH = hasher(config).hash(secrets.token_urlsafe(32))
    return _DECOY_HASH


def verify_password(config, stored_hash: str | None, password: str) -> bool:
    ph = hasher(config)
    target = stored_hash or decoy_hash(config)
    try:
        ph.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return stored_hash is not None


def new_session_token() -> str:
    """Opaque 256-bit random value; only its digest is persisted."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def digests_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


class RateLimiter:
    """In-process fixed-window limiter; sufficient for a local single install."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                hits = [t for t in self._hits.get(key, []) if now - t < self.window]
                self._hits[key] = hits
                if len(hits) >= self.max_attempts:
                    return False
            return True

    def record(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._hits.setdefault(key, []).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)


def origin_is_same(request, expected_hosts: set[str]) -> bool:
    """CSRF: state-changing requests must be same-origin.

    Origin is preferred; Referer is the fallback. A request with neither is
    rejected rather than trusted.
    """
    from urllib.parse import urlsplit

    origin = request.headers.get("origin")
    if origin == "null":
        return False
    candidate = origin or request.headers.get("referer")
    if not candidate:
        return False
    parts = urlsplit(candidate)
    if not parts.netloc:
        return False
    return parts.netloc.lower() in expected_hosts
