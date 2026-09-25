"""Local pinned embedding model (ADR 3): all-MiniLM-L6-v2, 384-dim, cosine.

The pinned weights are checksummed at startup; a mismatch is a fatal startup
error (requirement 9) because a silently different model would produce vectors
incompatible with the persisted index.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_model = None
_model_key: str | None = None


class ModelIntegrityError(RuntimeError):
    pass


def model_version(config) -> str:
    emb = config.section("embedding")
    return f"{emb['model_id']}@{emb['revision']}"


def _weight_files(cache_dir: Path) -> list[Path]:
    names = ("model.safetensors", "pytorch_model.bin")
    found: list[Path] = []
    for name in names:
        found.extend(sorted(cache_dir.rglob(name)))
    return found


def weights_digest(cache_dir: Path) -> str | None:
    files = _weight_files(cache_dir)
    if not files:
        return None
    # Prefer safetensors when both formats are cached.
    preferred = [f for f in files if f.name == "model.safetensors"] or files
    h = hashlib.sha256()
    with open(preferred[0], "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_model(config):
    """Load (downloading into the private cache on first run) and verify."""
    global _model, _model_key
    emb = config.section("embedding")
    key = model_version(config)
    with _lock:
        if _model is not None and _model_key == key:
            return _model
        from sentence_transformers import SentenceTransformer

        cache = config.model_cache_dir
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ.setdefault("HF_HOME", str(cache))
        model = SentenceTransformer(emb["model_id"], cache_folder=str(cache),
                                    revision=emb.get("revision") or None)
        verify_checksum(config)
        dim = model.get_sentence_embedding_dimension()
        if dim != int(emb["dimension"]):
            raise ModelIntegrityError(
                f"pinned embedding dimension {emb['dimension']} != loaded model dimension {dim}")
        _model, _model_key = model, key
        return model


def verify_checksum(config) -> str:
    """Fatal unless the cached pinned weights match the configured sha256."""
    emb = config.section("embedding")
    expected = (emb.get("weights_sha256") or "").strip()
    actual = weights_digest(config.model_cache_dir)
    if actual is None:
        raise ModelIntegrityError(
            f"pinned embedding model {emb['model_id']} is not present in {config.model_cache_dir}; "
            "run backend/dev.sh (or `python -m backend.app.dev --fetch-model`) to download it")
    if not expected:
        raise ModelIntegrityError(
            "embedding.weights_sha256 is not configured; measured digest is "
            f"{actual} -- set it in backend/config.yaml to pin the model")
    if expected != actual:
        raise ModelIntegrityError(
            "pinned embedding model checksum mismatch: configured "
            f"{expected[:16]}... but cached weights hash {actual[:16]}...")
    return actual


def embed_texts(config, texts: list[str]):
    model = load_model(config)
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                           show_progress_bar=False)
    return [[float(x) for x in v] for v in vectors]


def embed_query(config, text: str):
    return embed_texts(config, [text])[0]
