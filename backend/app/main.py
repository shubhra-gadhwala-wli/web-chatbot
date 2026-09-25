"""ASGI entrypoint. Startup is fail-fast (requirement 9)."""
from __future__ import annotations

import logging

from .api import create_app
from .config import ConfigError, load_config
from .embeddings import ModelIntegrityError
from .runtime import build_runtime, fail_fast

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def bootstrap():
    try:
        config = load_config()
        runtime = build_runtime(config)
    except (ConfigError, ModelIntegrityError) as exc:
        fail_fast(exc)
        raise
    runtime.repo.reconcile_stale_processing()
    return create_app(runtime)


app = bootstrap()
