"""Embedded LanceDB index: derived, rebuildable, never authoritative.

Rows carry account_id, document_id, chunk_id, generation, state and the vector.
Rows are written `staging` and promoted to `ready` only after the SQLite
`commit_chunks_and_ready` transaction succeeds, so a failure at any point can
leave no visible partial index.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Sequence

TABLE = "chunk_vectors"


def _quote(value: str) -> str:
    if "'" in value or "\\" in value or '"' in value:
        raise ValueError("opaque ids never contain quotes")
    return f"'{value}'"


class VectorStore:
    def __init__(self, directory: Path, dimension: int):
        import lancedb
        import pyarrow as pa

        self.dimension = dimension
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._db = lancedb.connect(str(self.directory))
        self._schema = pa.schema([
            pa.field("account_id", pa.string()),
            pa.field("document_id", pa.string()),
            pa.field("chunk_id", pa.string()),
            pa.field("generation", pa.int64()),
            pa.field("state", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
        ])
        if TABLE in self._db.table_names():
            self._table = self._db.open_table(TABLE)
        else:
            self._table = self._db.create_table(TABLE, schema=self._schema)

    # ------------------------------------------------------------- staging
    def stage(self, account_id: str, document_id: str, generation: int,
              rows: Sequence[dict]) -> None:
        payload = [{
            "account_id": account_id,
            "document_id": document_id,
            "chunk_id": r["chunk_id"],
            "generation": int(generation),
            "state": "staging",
            "vector": [float(x) for x in r["vector"]],
        } for r in rows]
        if not payload:
            return
        with self._lock:
            self._table.add(payload)

    def promote(self, account_id: str, document_id: str, generation: int) -> None:
        where = (f"account_id = {_quote(account_id)} AND document_id = {_quote(document_id)} "
                 f"AND generation = {int(generation)} AND state = 'staging'")
        with self._lock:
            try:
                self._table.update(where=where, values={"state": "ready"})
            except Exception:  # pragma: no cover - older lancedb API
                self._table.update(where=where, values_sql={"state": "'ready'"})

    def discard_staged(self, account_id: str, document_id: str, generation: int | None = None) -> None:
        clause = (f"account_id = {_quote(account_id)} AND document_id = {_quote(document_id)} "
                  f"AND state = 'staging'")
        if generation is not None:
            clause += f" AND generation = {int(generation)}"
        with self._lock:
            self._table.delete(clause)

    def delete_document(self, account_id: str, document_id: str) -> None:
        with self._lock:
            self._table.delete(
                f"account_id = {_quote(account_id)} AND document_id = {_quote(document_id)}")

    # ------------------------------------------------------------- reading
    def search(self, account_id: str, query_vector, limit: int) -> list[dict]:
        """Account predicate is applied as a LanceDB pre-filter BEFORE top-k."""
        where = f"account_id = {_quote(account_id)} AND state = 'ready'"
        self.last_where = where
        with self._lock:
            q = self._table.search([float(x) for x in query_vector])
            try:
                q = q.where(where, prefilter=True)
            except TypeError:  # pragma: no cover
                q = q.where(where)
            try:
                q = q.metric("cosine")
            except Exception:  # pragma: no cover
                pass
            rows = q.limit(limit).to_list()
        out = []
        for r in rows:
            distance = float(r.get("_distance", 1.0))
            out.append({
                "account_id": r["account_id"],
                "document_id": r["document_id"],
                "chunk_id": r["chunk_id"],
                "generation": int(r["generation"]),
                "similarity": 1.0 - distance,
            })
        return out

    def count(self, account_id: str | None = None, document_id: str | None = None,
              state: str | None = None) -> int:
        rows = self._table.to_arrow().to_pylist()
        def keep(r):
            return ((account_id is None or r["account_id"] == account_id)
                    and (document_id is None or r["document_id"] == document_id)
                    and (state is None or r["state"] == state))
        return sum(1 for r in rows if keep(r))
