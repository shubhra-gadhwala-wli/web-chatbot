"""DataAPI's stated integration gate: upgrade -> downgrade -> upgrade against a
synthetic two-account fixture."""
from __future__ import annotations

import datetime as dt
import sqlite3

from alembic import command
from alembic.config import Config as AlembicConfig

from backend.app.config import BACKEND_DIR


def _alembic(config):
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.db_path}")
    return cfg


def _two_account_fixture(db_path):
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    for account, doc, chunk in (("acct_a" * 6, "doc_a" * 8, "chk_a" * 8),
                                ("acct_b" * 6, "doc_b" * 8, "chk_b" * 8)):
        conn.execute("INSERT INTO accounts (id, password_hash, created_at) VALUES (?,?,?)",
                     (account, "argon2-placeholder", now))
        conn.execute("INSERT INTO account_emails (account_id, email_normalized, created_at) "
                     "VALUES (?,?,?)", (account, account + "@example.test", now))
        conn.execute(
            "INSERT INTO documents (id, account_id, original_filename, storage_key, content_sha256,"
            " byte_size, status, generation, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?, 'ready', 1, ?, ?)",
            (doc, account, "fixture.txt", f"{account}/{doc}", "0" * 64, 10, now, now))
        conn.execute(
            "INSERT INTO chunks (id, account_id, document_id, generation, ordinal, text,"
            " location_kind, location_start, location_end, embedding_model) "
            "VALUES (?,?,?,1,0,?, 'line', 1, 2, 'test-model@v0')",
            (chunk, account, doc, "fixture text"))
    conn.commit()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    return tables


def test_upgrade_downgrade_upgrade_with_two_account_fixture(config):
    cfg = _alembic(config)
    db = str(config.db_path)

    # config fixture already ran `upgrade head`
    tables = _two_account_fixture(db)
    assert {"accounts", "documents", "chunks", "citations", "sessions"} <= tables

    command.downgrade(cfg, "base")
    conn = sqlite3.connect(db)
    remaining = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "documents" not in remaining and "accounts" not in remaining

    command.upgrade(cfg, "head")
    tables = _two_account_fixture(db)
    assert {"accounts", "documents", "chunks", "upload_idempotency", "account_emails"} <= tables


def test_upgrade_is_idempotent(config):
    cfg = _alembic(config)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
