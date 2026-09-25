"""Idempotent developer entrypoint.

`python -m backend.app.dev` (or backend/dev.sh):
  1. creates ./.local-data and its subtrees with mode 0700,
  2. runs Alembic migrations (safe to re-run),
  3. downloads/verifies the pinned embedding model,
  4. launches the API and the ingest worker.

Running it twice neither errors nor duplicates state.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from .config import BACKEND_DIR, ConfigError, load_config
from .paths import init_data_dirs


def run_migrations(config) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.db_path}")
    command.upgrade(cfg, "head")
    try:
        os.chmod(config.db_path, 0o600)
    except OSError:
        pass


def fetch_model(config) -> str:
    from . import embeddings

    try:
        embeddings.verify_checksum(config)
        return "already present and verified"
    except embeddings.ModelIntegrityError:
        pass
    from sentence_transformers import SentenceTransformer

    emb = config.section("embedding")
    cache = config.model_cache_dir
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    SentenceTransformer(emb["model_id"], cache_folder=str(cache),
                        revision=emb.get("revision") or None)
    digest = embeddings.weights_digest(cache)
    embeddings.verify_checksum(config)
    return f"downloaded, sha256={digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend.dev")
    parser.add_argument("--migrate", action="store_true", help="only run migrations")
    parser.add_argument("--fetch-model", action="store_true", help="only fetch/verify the model")
    parser.add_argument("--print-model-digest", action="store_true")
    parser.add_argument("--no-worker", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_config(require_secret=not (args.print_model_digest))
    except ConfigError as exc:
        sys.stderr.write(f"FATAL startup error: {exc}\n")
        return 1

    init_data_dirs(config)
    print(f"[dev] data dir {config.data_dir} (0700)")

    if args.print_model_digest:
        from . import embeddings
        print(embeddings.weights_digest(config.model_cache_dir))
        return 0

    run_migrations(config)
    print("[dev] migrations at head")
    if args.migrate:
        return 0

    if os.environ.get("RAG_SKIP_MODEL_CHECK") != "1":
        print(f"[dev] embedding model: {fetch_model(config)}")
    if args.fetch_model:
        return 0

    env = dict(os.environ)
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app",
         "--host", config.host, "--port", str(config.port), "--no-access-log"],
        cwd=str(BACKEND_DIR.parent), env=env)
    worker = None
    if not args.no_worker:
        worker = subprocess.Popen([sys.executable, "-m", "backend.app.ingest"],
                                  cwd=str(BACKEND_DIR.parent), env=env)
    print(f"[dev] API http://{config.host}:{config.port}  worker pid={worker.pid if worker else '-'}")

    def shutdown(*_a):
        for proc in (worker, api):
            if proc and proc.poll() is None:
                proc.terminate()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    code = api.wait()
    shutdown()
    if worker:
        worker.wait(timeout=15)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
