"""R2: document extraction body, executed ONLY inside an OS-isolated child.

Contract with the parent (backend/app/extract.py):
    argv: <input_path> <output_path> <max_output_bytes>
    stdin: nothing.  stdout: one JSON status line.  Exit 0 on success.

Hardening applied here, before a single byte of untrusted input is touched:
  * `resource.setrlimit` caps on CPU seconds, address space, file size, core
    dumps and open files (the parent also passes a wall-clock timeout).
  * networking is disabled process-wide: socket creation raises.
  * the environment was already stripped by the parent.

Today this slice only decodes `.txt`. PDF support (PyMuPDF, with JS and forms
disabled and page/expansion bounds) drops into `extract_bytes` later without
changing the isolation boundary.
"""
from __future__ import annotations

import json
import sys


def harden(cpu_seconds: int, address_space: int, max_file_bytes: int) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, OSError):
        pass
    _disable_network()


def _disable_network() -> None:
    import socket

    def _denied(*_a, **_k):
        raise PermissionError("network access is disabled in the extraction sandbox")

    socket.socket = _denied  # type: ignore[assignment]
    socket.create_connection = _denied  # type: ignore[assignment]
    socket.socketpair = _denied  # type: ignore[assignment]
    socket.getaddrinfo = _denied  # type: ignore[assignment]


class ExtractionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def extract_bytes(data: bytes, max_output_bytes: int) -> tuple[str, int]:
    """Safe text decoding with bounded expansion. Returns (text, line_count)."""
    if len(data) == 0:
        raise ExtractionError("empty_file")
    if b"\x00" in data:
        raise ExtractionError("binary_content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ExtractionError("invalid_utf8")
    # Binary-looking heuristic: excessive C0 control characters.
    controls = sum(1 for ch in text[:65536] if ord(ch) < 32 and ch not in "\t\n\r")
    if controls > max(16, len(text[:65536]) // 100):
        raise ExtractionError("binary_content")
    # Normalise line endings and trim trailing whitespace; bounded expansion.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in normalized.split("\n")]
    normalized = "\n".join(lines).strip()
    if not normalized:
        raise ExtractionError("empty_extracted_text")
    encoded = normalized.encode("utf-8")
    if len(encoded) > max_output_bytes:
        raise ExtractionError("extracted_text_too_large")
    if len(encoded) > 4 * max(len(data), 1):
        raise ExtractionError("expansion_bound_exceeded")
    return normalized, normalized.count("\n") + 1


def main(argv: list[str]) -> int:
    input_path, output_path, max_output_bytes = argv[1], argv[2], int(argv[3])
    cpu_seconds = int(argv[4])
    address_space = int(argv[5])
    harden(cpu_seconds, address_space, max_output_bytes * 2)
    try:
        with open(input_path, "rb") as fh:
            data = fh.read(26214400 + 1)
        if len(data) > 26214400:
            raise ExtractionError("file_too_large")
        text, lines = extract_bytes(data, max_output_bytes)
    except ExtractionError as exc:
        sys.stdout.write(json.dumps({"ok": False, "code": exc.code}))
        return 2
    except MemoryError:
        sys.stdout.write(json.dumps({"ok": False, "code": "memory_limit"}))
        return 3
    except Exception:
        # Never leak content or paths from the sandbox.
        sys.stdout.write(json.dumps({"ok": False, "code": "extraction_failed"}))
        return 4
    import os

    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    sys.stdout.write(json.dumps({"ok": True, "lines": lines, "chars": len(text)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
