"""Parent side of the R2 isolated extraction boundary."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import safe_child


class ExtractionFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Extracted:
    path: Path
    text: str
    lines: int


def run_isolated_extraction(config, account_id: str, document_id: str,
                            source_path: Path) -> Extracted:
    sub = config.section("ingest").get("subprocess", {})
    out_dir = safe_child(config.work_dir, account_id)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Name is built only from the server-generated document id; the resolved
    # path is re-checked for containment before the child may write to it.
    out_path = (out_dir / f"{document_id}.txt").resolve()
    if config.work_dir.resolve() not in out_path.parents:
        raise ExtractionFailed("path_safety")

    cmd = [
        sys.executable, "-I", "-S", "-B",
        str(Path(__file__).with_name("extract_child.py")),
        str(source_path), str(out_path),
        str(int(sub.get("max_output_bytes", 33554432))),
        str(int(sub.get("cpu_seconds", 20))),
        str(int(sub.get("address_space_bytes", 1073741824))),
    ]
    # Restricted environment: no proxies, no HF tokens, no inherited secrets.
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0",
           "PYTHONPATH": ""}
    try:
        proc = subprocess.run(cmd, capture_output=True, env=env, cwd="/",
                              timeout=float(sub.get("wall_seconds", 30)))
    except subprocess.TimeoutExpired:
        raise ExtractionFailed("extraction_timeout")
    try:
        status = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        status = {}
    if proc.returncode != 0 or not status.get("ok"):
        raise ExtractionFailed(str(status.get("code") or "extraction_failed"))
    text = out_path.read_text(encoding="utf-8")
    return Extracted(path=out_path, text=text, lines=int(status["lines"]))
