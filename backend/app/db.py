"""SQLite access. SQLite is the authority for ownership and ready state."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

_local = threading.local()


def connect(db_path: Path) -> sqlite3.Connection:
    first = not db_path.exists()
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None,
                           check_same_thread=False)
    if first:
        try:
            os.chmod(db_path, 0o600)
        except OSError:  # pragma: no cover
            pass
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        c = getattr(_local, "conns", None)
        if c is None:
            c = _local.conns = {}
        key = str(self.db_path)
        if key not in c:
            c[key] = connect(self.db_path)
        return c[key]

    @contextmanager
    def tx(self):
        conn = self.conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def close(self) -> None:
        c = getattr(_local, "conns", None) or {}
        conn = c.pop(str(self.db_path), None)
        if conn is not None:
            conn.close()
