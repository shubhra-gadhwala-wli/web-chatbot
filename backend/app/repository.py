"""Account-scoped repository implementing data-api/repository-contract.md.

Every public method takes `account_id` first and every SQL predicate is
`(account_id, id)`. A missing record and a record owned by another account both
raise `NotFound`; callers cannot distinguish them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import audit
from .db import Database
from .errors import IdempotencyConflict, NotFound, StateConflict, ValidationError
from .ids import new_id
from .paths import PathSafetyError, safe_child


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


@dataclass
class ChunkInput:
    ordinal: int
    text: str
    location_kind: str
    location_start: int
    location_end: int
    embedding_model: str
    chunk_id: str
    vector: Sequence[float] | None = None


class Repository:
    def __init__(self, db: Database, files_dir: Path, vectors, request_id_provider=None):
        self.db = db
        self.files_dir = Path(files_dir)
        self.vectors = vectors
        self._request_id = request_id_provider or (lambda: None)

    # ---------------------------------------------------------------- audit
    def _deny(self, account_id: str | None, resource_type: str, opaque_id: str | None) -> NotFound:
        """Emit the redacted audit event *after* the authorization predicate
        has failed, then raise the indistinguishable NotFound."""
        audit.emit("cross_account_denied", account_id, resource_type, opaque_id, self._request_id())
        return NotFound(resource_type, opaque_id)

    # ------------------------------------------------------------- accounts
    def create_account(self, email_normalized: str, password_hash: str) -> str:
        account_id = new_id()
        now = _now()
        with self.db.tx() as c:
            exists = c.execute("SELECT 1 FROM account_emails WHERE email_normalized = ?",
                               (email_normalized,)).fetchone()
            if exists:
                raise StateConflict("account", "exists")
            c.execute("INSERT INTO accounts (id, password_hash, created_at) VALUES (?,?,?)",
                      (account_id, password_hash, now))
            c.execute("INSERT INTO account_emails (account_id, email_normalized, created_at) VALUES (?,?,?)",
                      (account_id, email_normalized, now))
        return account_id

    def find_account_by_email(self, email_normalized: str) -> dict | None:
        row = self.db.conn().execute(
            "SELECT a.id AS id, a.password_hash AS password_hash, a.disabled_at AS disabled_at "
            "FROM account_emails e JOIN accounts a ON a.id = e.account_id "
            "WHERE e.email_normalized = ?", (email_normalized,)).fetchone()
        return dict(row) if row else None

    def update_password_hash(self, account_id: str, password_hash: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (password_hash, account_id))

    # ------------------------------------------------------------- sessions
    def create_session(self, account_id: str, token_digest: str, ttl_days: int) -> dict:
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        expires = now + dt.timedelta(days=ttl_days)
        sid = new_id()
        with self.db.tx() as c:
            c.execute("INSERT INTO sessions (id, account_id, token_digest, created_at, expires_at) "
                      "VALUES (?,?,?,?,?)",
                      (sid, account_id, token_digest,
                       now.isoformat(sep=" ", timespec="seconds"),
                       expires.isoformat(sep=" ", timespec="seconds")))
        return {"id": sid, "account_id": account_id, "expires_at": expires}

    def session_by_digest(self, token_digest: str) -> dict | None:
        row = self.db.conn().execute(
            "SELECT id, account_id, expires_at, revoked_at FROM sessions WHERE token_digest = ?",
            (token_digest,)).fetchone()
        if not row:
            return None
        if row["revoked_at"] is not None:
            return None
        if dt.datetime.fromisoformat(row["expires_at"]) <= dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):
            return None
        return dict(row)

    def revoke_session(self, account_id: str, session_id: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND account_id = ? AND revoked_at IS NULL",
                      (_now(), session_id, account_id))

    def revoke_all_sessions(self, account_id: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE sessions SET revoked_at = ? WHERE account_id = ? AND revoked_at IS NULL",
                      (_now(), account_id))

    # ------------------------------------------------------------ documents
    def storage_path(self, account_id: str, document_id: str) -> Path:
        """Path is built only from server-generated opaque IDs (R3)."""
        return safe_child(self.files_dir, account_id, document_id)

    def create_upload(self, account_id: str, original_filename: str, byte_size: int,
                      content_sha256: str, idempotency_key: str) -> dict:
        if byte_size < 0 or byte_size > 26214400:
            raise ValidationError("file_too_large", "file")
        if not idempotency_key or not (16 <= len(idempotency_key) <= 128):
            raise ValidationError("validation_error", "Idempotency-Key")
        request_hash = hashlib.sha256(
            json.dumps([original_filename, byte_size, content_sha256], sort_keys=True).encode()
        ).hexdigest()

        with self.db.tx() as c:
            prior = c.execute(
                "SELECT document_id, request_hash FROM upload_idempotency "
                "WHERE account_id = ? AND idempotency_key = ?",
                (account_id, idempotency_key)).fetchone()
            if prior:
                if prior["request_hash"] != request_hash:
                    raise IdempotencyConflict(idempotency_key)
                doc = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                                (account_id, prior["document_id"])).fetchone()
                if doc is None:
                    raise IdempotencyConflict(idempotency_key)
                return dict(doc)

            document_id = new_id()
            # storage key is generated from the document id, never the client name
            storage_key = f"{account_id}/{document_id}"
            try:
                self.storage_path(account_id, document_id)
            except PathSafetyError as exc:  # pragma: no cover - ids are generated
                raise ValidationError("validation_error", "storage_key") from exc
            now = _now()
            c.execute(
                "INSERT INTO documents (id, account_id, original_filename, storage_key, "
                "content_sha256, byte_size, status, generation, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?, 'uploaded', 1, ?, ?)",
                (document_id, account_id, original_filename[:255], storage_key,
                 content_sha256, byte_size, now, now))
            c.execute("INSERT INTO upload_idempotency (account_id, idempotency_key, request_hash, "
                      "document_id, created_at) VALUES (?,?,?,?,?)",
                      (account_id, idempotency_key, request_hash, document_id, now))
            doc = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            return dict(doc)

    def get_document(self, account_id: str, document_id: str) -> dict:
        row = self.db.conn().execute(
            "SELECT * FROM documents WHERE account_id = ? AND id = ? AND deleted_at IS NULL",
            (account_id, document_id)).fetchone()
        if row is None:
            raise self._deny(account_id, "document", document_id)
        return dict(row)

    def list_documents(self, account_id: str, cursor: str | None, limit: int) -> tuple[list[dict], str | None]:
        params: list[Any] = [account_id]
        sql = ("SELECT * FROM documents WHERE account_id = ? AND deleted_at IS NULL")
        if cursor:
            sql += " AND (created_at, id) < (SELECT created_at, id FROM documents WHERE account_id = ? AND id = ?)"
            params += [account_id, cursor]
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit + 1)
        rows = [dict(r) for r in self.db.conn().execute(sql, params).fetchall()]
        next_cursor = rows[limit]["id"] if len(rows) > limit else None
        return rows[:limit], next_cursor

    def claim_ingest(self, account_id: str, document_id: str) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            if row is None or row["deleted_at"] is not None:
                raise self._deny(account_id, "document", document_id)
            if row["status"] != "uploaded":
                raise StateConflict("document", row["status"])
            c.execute("UPDATE documents SET status = 'processing', updated_at = ? "
                      "WHERE account_id = ? AND id = ? AND status = 'uploaded'",
                      (_now(), account_id, document_id))
            row = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            return dict(row)

    def commit_chunks_and_ready(self, account_id: str, document_id: str, generation: int,
                                chunks: Iterable[ChunkInput]) -> dict:
        """Single SQLite transaction: verify owner + `processing`, insert scoped
        chunks, mark ready, record generation. Vector rows must already be
        staged; the caller promotes them only after this returns."""
        chunks = list(chunks)
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            if row is None or row["deleted_at"] is not None:
                raise self._deny(account_id, "document", document_id)
            if row["status"] != "processing":
                raise StateConflict("document", row["status"])
            if row["generation"] != generation:
                raise StateConflict("document", f"generation:{row['generation']}")
            if not chunks:
                raise ValidationError("validation_error", "chunks")
            for ch in chunks:
                c.execute(
                    "INSERT INTO chunks (id, account_id, document_id, generation, ordinal, text, "
                    "location_kind, location_start, location_end, embedding_model) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ch.chunk_id, account_id, document_id, generation, ch.ordinal, ch.text,
                     ch.location_kind, ch.location_start, ch.location_end, ch.embedding_model))
            c.execute("UPDATE documents SET status = 'ready', generation = ?, failure_code = NULL, "
                      "updated_at = ? WHERE account_id = ? AND id = ? AND status = 'processing'",
                      (generation, _now(), account_id, document_id))
            return dict(c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                                  (account_id, document_id)).fetchone())

    def fail_ingest(self, account_id: str, document_id: str, failure_code: str) -> dict | None:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            if row is None:
                raise self._deny(account_id, "document", document_id)
            if row["deleted_at"] is not None or row["status"] == "deleting":
                return None  # deletion wins over a concurrent failure
            if row["status"] not in ("uploaded", "processing"):
                raise StateConflict("document", row["status"])
            c.execute("UPDATE documents SET status = 'failed', failure_code = ?, updated_at = ? "
                      "WHERE account_id = ? AND id = ?", (failure_code[:64], _now(), account_id, document_id))
            c.execute("DELETE FROM chunks WHERE account_id = ? AND document_id = ?",
                      (account_id, document_id))
            return dict(c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                                  (account_id, document_id)).fetchone())

    def delete_document(self, account_id: str, document_id: str) -> None:
        """Idempotent: tombstone, then remove file, chunks, citations, vectors."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM documents WHERE account_id = ? AND id = ?",
                            (account_id, document_id)).fetchone()
            if row is None:
                raise self._deny(account_id, "document", document_id)
            c.execute("UPDATE documents SET status = 'deleting', deleted_at = COALESCE(deleted_at, ?), "
                      "updated_at = ? WHERE account_id = ? AND id = ?",
                      (_now(), _now(), account_id, document_id))
        # outside the tombstone transaction: derived data
        if self.vectors is not None:
            self.vectors.delete_document(account_id, document_id)
        try:
            path = self.storage_path(account_id, document_id)
            if path.exists() and not path.is_symlink():
                path.unlink()
        except (PathSafetyError, OSError):
            pass
        with self.db.tx() as c:
            c.execute("DELETE FROM citations WHERE account_id = ? AND document_id = ?",
                      (account_id, document_id))
            c.execute("DELETE FROM chunks WHERE account_id = ? AND document_id = ?",
                      (account_id, document_id))
            c.execute("DELETE FROM documents WHERE account_id = ? AND id = ?",
                      (account_id, document_id))

    def next_uploaded_document(self) -> dict | None:
        row = self.db.conn().execute(
            "SELECT * FROM documents WHERE status = 'uploaded' AND deleted_at IS NULL "
            "ORDER BY created_at LIMIT 1").fetchone()
        return dict(row) if row else None

    def reconcile_stale_processing(self) -> int:
        """Startup reconciliation: an interrupted worker leaves `processing`
        rows with no ready visibility. They become `failed`, never `ready`."""
        rows = self.db.conn().execute(
            "SELECT account_id, id FROM documents WHERE status = 'processing' AND deleted_at IS NULL"
        ).fetchall()
        for r in rows:
            if self.vectors is not None:
                self.vectors.delete_document(r["account_id"], r["id"])
            try:
                self.fail_ingest(r["account_id"], r["id"], "worker_interrupted")
            except (StateConflict, NotFound):
                pass
        return len(rows)

    # --------------------------------------------------------------- chunks
    def get_chunk(self, account_id: str, document_id: str, chunk_id: str) -> dict:
        row = self.db.conn().execute(
            "SELECT c.* FROM chunks c JOIN documents d ON d.account_id = c.account_id AND d.id = c.document_id "
            "WHERE c.account_id = ? AND c.document_id = ? AND c.id = ? "
            "AND d.account_id = ? AND d.status = 'ready' AND d.deleted_at IS NULL "
            "AND d.generation = c.generation",
            (account_id, document_id, chunk_id, account_id)).fetchone()
        if row is None:
            raise self._deny(account_id, "chunk", chunk_id)
        return dict(row)

    def has_ready_documents(self, account_id: str) -> bool:
        row = self.db.conn().execute(
            "SELECT 1 FROM documents WHERE account_id = ? AND status = 'ready' AND deleted_at IS NULL LIMIT 1",
            (account_id,)).fetchone()
        return row is not None

    def retrieve_ready_chunks(self, account_id: str, query_vector, limit: int = 5) -> list[dict]:
        """LanceDB is queried with the bound account predicate BEFORE top-k;
        every candidate is then rechecked against SQLite, which is the only
        authority for ownership, ready state and generation."""
        if self.vectors is None:
            return []
        candidates = self.vectors.search(account_id, query_vector, limit)
        verified: list[dict] = []
        for cand in candidates:
            if cand["account_id"] != account_id:
                # Defence in depth: never trust the index's own scope field.
                audit.emit("cross_account_denied", account_id, "vector", cand.get("chunk_id"),
                           self._request_id())
                continue
            row = self.db.conn().execute(
                "SELECT c.id AS chunk_id, c.document_id AS document_id, c.text AS text, "
                "c.ordinal AS ordinal, c.location_kind AS location_kind, "
                "c.location_start AS location_start, c.location_end AS location_end, "
                "d.original_filename AS document_name "
                "FROM chunks c JOIN documents d ON d.account_id = c.account_id AND d.id = c.document_id "
                "WHERE c.account_id = ? AND c.document_id = ? AND c.id = ? AND c.generation = ? "
                "AND d.account_id = ? AND d.status = 'ready' AND d.deleted_at IS NULL "
                "AND d.generation = c.generation",
                (account_id, cand["document_id"], cand["chunk_id"], cand["generation"], account_id)
            ).fetchone()
            if row is None:
                continue
            item = dict(row)
            item["similarity"] = cand["similarity"]
            verified.append(item)
        return verified

    # -------------------------------------------------------- conversations
    def create_conversation(self, account_id: str, title: str) -> dict:
        cid = new_id()
        now = _now()
        with self.db.tx() as c:
            c.execute("INSERT INTO conversations (id, account_id, title, created_at, updated_at) "
                      "VALUES (?,?,?,?,?)", (cid, account_id, title[:200], now, now))
            return dict(c.execute("SELECT * FROM conversations WHERE account_id = ? AND id = ?",
                                  (account_id, cid)).fetchone())

    def get_conversation(self, account_id: str, conversation_id: str) -> dict:
        row = self.db.conn().execute("SELECT * FROM conversations WHERE account_id = ? AND id = ?",
                                     (account_id, conversation_id)).fetchone()
        if row is None:
            raise self._deny(account_id, "conversation", conversation_id)
        return dict(row)

    def rename_conversation(self, account_id: str, conversation_id: str, title: str) -> dict:
        self.get_conversation(account_id, conversation_id)
        with self.db.tx() as c:
            c.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE account_id = ? AND id = ?",
                      (title[:200], _now(), account_id, conversation_id))
        return self.get_conversation(account_id, conversation_id)

    def list_conversations(self, account_id: str, cursor: str | None, limit: int):
        params: list[Any] = [account_id]
        sql = "SELECT * FROM conversations WHERE account_id = ?"
        if cursor:
            sql += (" AND (updated_at, id) < (SELECT updated_at, id FROM conversations "
                    "WHERE account_id = ? AND id = ?)")
            params += [account_id, cursor]
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit + 1)
        rows = [dict(r) for r in self.db.conn().execute(sql, params).fetchall()]
        return rows[:limit], (rows[limit]["id"] if len(rows) > limit else None)

    def list_messages(self, account_id: str, conversation_id: str, cursor: str | None, limit: int):
        self.get_conversation(account_id, conversation_id)
        params: list[Any] = [account_id, conversation_id]
        sql = "SELECT * FROM messages WHERE account_id = ? AND conversation_id = ?"
        if cursor:
            sql += " AND sequence > (SELECT sequence FROM messages WHERE account_id = ? AND id = ?)"
            params += [account_id, cursor]
        sql += " ORDER BY sequence LIMIT ?"
        params.append(limit + 1)
        rows = [dict(r) for r in self.db.conn().execute(sql, params).fetchall()]
        return rows[:limit], (rows[limit]["id"] if len(rows) > limit else None)

    def find_message_by_client_request(self, account_id: str, client_request_id: str) -> dict | None:
        row = self.db.conn().execute(
            "SELECT * FROM messages WHERE account_id = ? AND client_request_id = ?",
            (account_id, client_request_id)).fetchone()
        return dict(row) if row else None

    def persist_answer(self, account_id: str, conversation_id: str, user_text: str,
                       client_request_id: str, request_hash: str, answer_text: str,
                       status: str, citation_chunks: Sequence[dict]) -> tuple[dict, dict]:
        """Persist the user message, assistant message and citations in one
        transaction."""
        with self.db.tx() as c:
            conv = c.execute("SELECT * FROM conversations WHERE account_id = ? AND id = ?",
                             (account_id, conversation_id)).fetchone()
            if conv is None:
                raise self._deny(account_id, "conversation", conversation_id)
            seq_row = c.execute("SELECT COALESCE(MAX(sequence), 0) AS s FROM messages "
                                "WHERE conversation_id = ?", (conversation_id,)).fetchone()
            seq = int(seq_row["s"])
            now = _now()
            user_id, assistant_id = new_id(), new_id()
            c.execute("INSERT INTO messages (id, account_id, conversation_id, sequence, role, content, "
                      "status, client_request_id, request_hash, created_at) "
                      "VALUES (?,?,?,?, 'user', ?, 'completed', ?, ?, ?)",
                      (user_id, account_id, conversation_id, seq + 1, user_text,
                       client_request_id, request_hash, now))
            c.execute("INSERT INTO messages (id, account_id, conversation_id, sequence, role, content, "
                      "status, client_request_id, request_hash, created_at) "
                      "VALUES (?,?,?,?, 'assistant', ?, ?, NULL, NULL, ?)",
                      (assistant_id, account_id, conversation_id, seq + 2, answer_text, status, now))
            for ch in citation_chunks:
                # Re-verify scope inside the same transaction before persisting.
                ok = c.execute(
                    "SELECT 1 FROM chunks WHERE account_id = ? AND id = ? AND document_id = ?",
                    (account_id, ch["chunk_id"], ch["document_id"])).fetchone()
                if ok is None:
                    raise self._deny(account_id, "chunk", ch.get("chunk_id"))
                c.execute("INSERT OR IGNORE INTO citations (id, account_id, message_id, chunk_id, document_id) "
                          "VALUES (?,?,?,?,?)",
                          (new_id(), account_id, assistant_id, ch["chunk_id"], ch["document_id"]))
            c.execute("UPDATE conversations SET updated_at = ? WHERE account_id = ? AND id = ?",
                      (now, account_id, conversation_id))
            user_msg = dict(c.execute("SELECT * FROM messages WHERE account_id = ? AND id = ?",
                                      (account_id, user_id)).fetchone())
            assistant_msg = dict(c.execute("SELECT * FROM messages WHERE account_id = ? AND id = ?",
                                           (account_id, assistant_id)).fetchone())
        return user_msg, assistant_msg

    def get_citation(self, account_id: str, message_id: str, chunk_id: str) -> dict:
        """Join citation -> message -> conversation and chunk/document with an
        explicit `account_id` predicate on every joined table."""
        row = self.db.conn().execute(
            "SELECT ct.id AS citation_id, ch.id AS chunk_id, ch.document_id AS document_id, "
            "ch.text AS text, ch.location_kind AS location_kind, ch.location_start AS location_start, "
            "ch.location_end AS location_end, d.original_filename AS document_name "
            "FROM citations ct "
            "JOIN messages m ON m.account_id = ct.account_id AND m.id = ct.message_id "
            "JOIN conversations cv ON cv.account_id = m.account_id AND cv.id = m.conversation_id "
            "JOIN chunks ch ON ch.account_id = ct.account_id AND ch.id = ct.chunk_id "
            "JOIN documents d ON d.account_id = ch.account_id AND d.id = ch.document_id "
            "WHERE ct.account_id = ? AND m.account_id = ? AND cv.account_id = ? "
            "AND ch.account_id = ? AND d.account_id = ? "
            "AND ct.message_id = ? AND ct.chunk_id = ? "
            "AND d.deleted_at IS NULL AND d.status = 'ready'",
            (account_id, account_id, account_id, account_id, account_id, message_id, chunk_id)
        ).fetchone()
        if row is None:
            raise self._deny(account_id, "citation", chunk_id)
        return dict(row)

    def citations_for_message(self, account_id: str, message_id: str) -> list[dict]:
        rows = self.db.conn().execute(
            "SELECT ct.chunk_id AS chunk_id, ct.document_id AS document_id, "
            "ch.location_kind AS location_kind, ch.location_start AS location_start, "
            "ch.location_end AS location_end, d.original_filename AS document_name "
            "FROM citations ct "
            "JOIN chunks ch ON ch.account_id = ct.account_id AND ch.id = ct.chunk_id "
            "JOIN documents d ON d.account_id = ct.account_id AND d.id = ct.document_id "
            "WHERE ct.account_id = ? AND ct.message_id = ? AND d.deleted_at IS NULL",
            (account_id, message_id)).fetchall()
        return [dict(r) for r in rows]

    def citations_for_messages(self, account_id: str, message_ids: Sequence[str]) -> dict[str, list[dict]]:
        """Batch lookup to avoid N+1 queries when replaying a message list."""
        if not message_ids:
            return {}
        placeholders = ",".join("?" for _ in message_ids)
        rows = self.db.conn().execute(
            "SELECT ct.message_id AS message_id, ct.chunk_id AS chunk_id, ct.document_id AS document_id, "
            "ch.location_kind AS location_kind, ch.location_start AS location_start, "
            "ch.location_end AS location_end, d.original_filename AS document_name "
            "FROM citations ct "
            "JOIN chunks ch ON ch.account_id = ct.account_id AND ch.id = ct.chunk_id "
            "JOIN documents d ON d.account_id = ct.account_id AND d.id = ct.document_id "
            f"WHERE ct.account_id = ? AND ct.message_id IN ({placeholders}) AND d.deleted_at IS NULL",
            (account_id, *message_ids)).fetchall()
        by_message: dict[str, list[dict]] = {mid: [] for mid in message_ids}
        for r in rows:
            by_message[r["message_id"]].append(dict(r))
        return by_message
