"""R3: every identifier is server generated, 256-bit, non-sequential and never
derived from client input."""
from __future__ import annotations

import re
import secrets

OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")


def new_id() -> str:
    """256 bits of randomness, URL-safe, 43 chars (matches OpaqueId pattern)."""
    return secrets.token_urlsafe(32)


def is_opaque_id(value: object) -> bool:
    return isinstance(value, str) and bool(OPAQUE_ID_RE.match(value))
