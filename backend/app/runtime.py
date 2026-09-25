"""Process-wide runtime wiring plus the fail-fast startup gate (requirement 9)."""
from __future__ import annotations

import contextvars
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import audit, embeddings
from .config import Config, ConfigError, load_config
from .db import Database
from .paths import ensure_private_dir, init_data_dirs
from .repository import Repository
from .vectors import VectorStore

current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_request_id", default=None)


@dataclass
class Runtime:
    config: Config
    db: Database
    repo: Repository
    vectors: VectorStore


def preflight(config: Config) -> None:
    """Fail fast with a clear message; the caller exits non-zero."""
    init_data_dirs(config)
    probe = config.data_dir / ".write-probe"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"data directory {config.data_dir} is not writable: {exc}") from exc
    if not config.db_path.exists():
        raise ConfigError(
            f"SQLite database {config.db_path} does not exist; run backend/dev.sh "
            "(or `python -m backend.app.dev --migrate`) to apply migrations first")
    if os.environ.get("RAG_SKIP_MODEL_CHECK") != "1":
        embeddings.verify_checksum(config)


def build_runtime(config: Config | None = None, *, run_preflight: bool = True) -> Runtime:
    config = config or load_config()
    if run_preflight:
        preflight(config)
    else:
        init_data_dirs(config)
    audit.configure(config.data_dir / "audit.log")
    db = Database(config.db_path)
    vectors = VectorStore(config.vectors_dir, int(config.section("embedding")["dimension"]))
    repo = Repository(db, config.files_dir, vectors,
                      request_id_provider=lambda: current_request_id.get())
    return Runtime(config=config, db=db, repo=repo, vectors=vectors)


def fail_fast(exc: Exception) -> None:  # pragma: no cover - process exit path
    sys.stderr.write(f"FATAL startup error: {exc}\n")
    raise SystemExit(1)
