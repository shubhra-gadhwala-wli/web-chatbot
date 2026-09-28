"""R5 audit hook.

`cross_account_denied` is emitted only after an authorization predicate has
failed. It carries the actor account id, resource type, the opaque id that was
presented and the request id -- never content, filenames, paths, vectors,
session tokens, or any field that would prove whether the resource exists for
another account.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_LOG = logging.getLogger("audit")
_lock = threading.Lock()
_sink_path: Path | None = None
_memory: list[dict] = []

_ALLOWED_FIELDS = {"event", "actor_account_id", "resource_type", "opaque_id", "request_id", "ts"}


def configure(path: Path | None) -> None:
    global _sink_path
    _sink_path = path


def emit(event: str, actor_account_id: str | None, resource_type: str, opaque_id: str | None,
         request_id: str | None = None) -> dict:
    import datetime as _dt

    record = {
        "event": event,
        "actor_account_id": actor_account_id,
        "resource_type": resource_type,
        "opaque_id": opaque_id,
        "request_id": request_id,
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    assert set(record) <= _ALLOWED_FIELDS, "audit record carries a disallowed field"
    line = json.dumps(record, sort_keys=True)
    with _lock:
        _memory.append(record)
        if _sink_path is not None:
            import os

            fd = os.open(_sink_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)
    _LOG.info("audit %s", line)
    return record


def emit_login_failure(reason: str, request_id: str | None = None) -> dict:
    """Login failures are logged without password, email or account existence."""
    return emit("login_failed", None, reason, None, request_id)


def recent(event: str | None = None) -> list[dict]:
    with _lock:
        if event is None:
            return list(_memory)
        return [r for r in _memory if r["event"] == event]


def reset() -> None:
    with _lock:
        _memory.clear()
