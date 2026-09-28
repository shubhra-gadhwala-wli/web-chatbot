from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("RAG_SESSION_SECRET", "test-secret-value-that-is-long-enough-1234567890")
os.environ.setdefault("RAG_SKIP_MODEL_CHECK", "1")

from backend.app import audit, embeddings  # noqa: E402
from backend.app.config import load_config  # noqa: E402
from backend.app.dev import run_migrations  # noqa: E402
from backend.app.runtime import build_runtime  # noqa: E402


def deterministic_vector(text: str, dim: int = 384) -> list[float]:
    """Stable pseudo-embedding used by the fast tests. The real pinned model is
    exercised by test_end_to_end_real_model.py."""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        out.extend((b - 127.5) / 127.5 for b in digest)
        counter += 1
    vec = out[:dim]
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / ".local-data"))
    monkeypatch.setenv("RAG_SESSION_SECRET", "test-secret-value-that-is-long-enough-1234567890")
    monkeypatch.setenv("RAG_SKIP_MODEL_CHECK", "1")
    cfg = load_config()
    (tmp_path / ".local-data").mkdir(parents=True, exist_ok=True, mode=0o700)
    run_migrations(cfg)
    return cfg


@pytest.fixture
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_texts",
                        lambda cfg, texts: [deterministic_vector(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query",
                        lambda cfg, text: deterministic_vector(text))
    monkeypatch.setattr(embeddings, "model_version", lambda cfg: "test-model@v0")


@pytest.fixture
def runtime(config):
    audit.reset()
    return build_runtime(config, run_preflight=False)
