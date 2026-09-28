"""The single dev entrypoint must be idempotent and fail fast."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.config import ConfigError, load_config
from backend.app.dev import main as dev_main

ROOT = Path(__file__).resolve().parents[2]


def test_dev_migrate_twice_is_idempotent(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / ".local-data"
    monkeypatch.setenv("RAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RAG_SKIP_MODEL_CHECK", "1")
    monkeypatch.setenv("RAG_SESSION_SECRET", "x" * 40)

    assert dev_main(["--migrate"]) == 0
    first = sorted(p.name for p in data_dir.iterdir())
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700

    assert dev_main(["--migrate"]) == 0
    assert sorted(p.name for p in data_dir.iterdir()) == first

    cfg = load_config()
    import sqlite3
    conn = sqlite3.connect(cfg.db_path)
    versions = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    conn.close()
    assert len(versions) == 1 and accounts == 0, "re-running must not duplicate state"


def test_startup_fails_fast_without_session_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / ".local-data"))
    monkeypatch.delenv("RAG_SESSION_SECRET", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "RAG_SESSION_SECRET" in str(exc.value)


def test_startup_fails_fast_on_model_checksum_mismatch(tmp_path, monkeypatch):
    from backend.app import embeddings
    from backend.app.runtime import preflight

    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / ".local-data"))
    monkeypatch.setenv("RAG_SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("RAG_SKIP_MODEL_CHECK", raising=False)
    cfg = load_config()
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.db_path.touch()
    monkeypatch.setattr(embeddings, "weights_digest", lambda cache: "deadbeef" * 8)
    with pytest.raises(embeddings.ModelIntegrityError) as exc:
        preflight(cfg)
    assert "checksum mismatch" in str(exc.value)


def test_dev_entrypoint_exits_nonzero_with_clear_message(tmp_path):
    env = dict(os.environ)
    env["RAG_DATA_DIR"] = str(tmp_path / ".local-data")
    env.pop("RAG_SESSION_SECRET", None)
    proc = subprocess.run([sys.executable, "-m", "backend.app.dev", "--migrate"],
                          cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert proc.returncode == 1
    assert "FATAL startup error" in proc.stderr and "RAG_SESSION_SECRET" in proc.stderr
