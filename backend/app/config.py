"""Configuration loading (ADR 2): YAML holds non-secret defaults, environment
variables override and are the only source of secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = BACKEND_DIR / "config.yaml"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ConfigError(RuntimeError):
    """Fatal startup misconfiguration."""


@dataclass
class Config:
    raw: dict[str, Any]
    data_dir: Path
    session_secret: str
    generation_api_key: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name) or {})

    # convenience accessors -------------------------------------------------
    @property
    def host(self) -> str:
        return os.environ.get("RAG_HOST") or self.section("app").get("host", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(os.environ.get("RAG_PORT") or self.section("app").get("port", 8080))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def generation_base_url(self) -> str:
        return os.environ.get("RAG_GENERATION_BASE_URL") or self.section("generation")["base_url"]

    @property
    def generation_model(self) -> str:
        return os.environ.get("RAG_GENERATION_MODEL") or self.section("generation")["model"]


def load_config(config_path: Path | None = None, *, require_secret: bool = True) -> Config:
    env_file = Path(os.environ.get("RAG_ENV_FILE", str(BACKEND_DIR / ".env")))
    _load_dotenv(env_file)
    path = config_path or Path(os.environ.get("RAG_CONFIG", DEFAULT_CONFIG))
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    data_dir = Path(os.environ.get("RAG_DATA_DIR") or raw.get("app", {}).get("data_dir", "./.local-data"))
    data_dir = data_dir.expanduser().resolve()

    secret = os.environ.get("RAG_SESSION_SECRET", "")
    if require_secret and len(secret) < 32:
        raise ConfigError(
            "RAG_SESSION_SECRET is missing or shorter than 32 characters. "
            "Copy backend/.env.sample to backend/.env and generate one with: "
            "python3 -c \"import secrets;print(secrets.token_urlsafe(48))\""
        )

    url = raw.get("generation", {}).get("base_url", "")
    if "@" in url.split("//", 1)[-1].split("/", 1)[0]:
        raise ConfigError("generation.base_url must not contain embedded credentials")

    return Config(
        raw=raw,
        data_dir=data_dir,
        session_secret=secret,
        generation_api_key=os.environ.get("RAG_GENERATION_API_KEY", ""),
    )
