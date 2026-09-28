from __future__ import annotations

import secrets

from backend.app import auth
from backend.app.ids import new_id


def make_account(runtime, email: str, password: str = "correct horse battery staple") -> str:
    return runtime.repo.create_account(email, auth.hasher(runtime.config).hash(password))


def login_cookie(runtime, account_id: str) -> dict:
    token = auth.new_session_token()
    runtime.repo.create_session(account_id, auth.token_digest(token), 14)
    return {auth.SESSION_COOKIE: token}


def ready_document(runtime, account_id: str, filename: str, text: str, vector_fn) -> tuple[str, list[str]]:
    """Upload -> claim -> stage vectors -> commit -> promote, using the real
    repository/vector paths."""
    from backend.app.repository import ChunkInput

    repo, vectors = runtime.repo, runtime.vectors
    doc = repo.create_upload(account_id, filename, len(text.encode()),
                             "0" * 64, secrets.token_urlsafe(16))
    path = repo.storage_path(account_id, doc["id"])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    repo.claim_ingest(account_id, doc["id"])
    chunk_ids = []
    chunks, staged = [], []
    for ordinal, paragraph in enumerate(p for p in text.split("\n\n") if p.strip()):
        chunk_id = new_id()
        chunk_ids.append(chunk_id)
        chunks.append(ChunkInput(ordinal=ordinal, text=paragraph, location_kind="line",
                                 location_start=ordinal + 1, location_end=ordinal + 2,
                                 embedding_model="test-model@v0", chunk_id=chunk_id))
        staged.append({"chunk_id": chunk_id, "vector": vector_fn(paragraph)})
    vectors.stage(account_id, doc["id"], 1, staged)
    repo.commit_chunks_and_ready(account_id, doc["id"], 1, chunks)
    vectors.promote(account_id, doc["id"], 1)
    return doc["id"], chunk_ids


def client(runtime):
    from fastapi.testclient import TestClient

    from backend.app.api import create_app

    c = TestClient(create_app(runtime), base_url="http://127.0.0.1:8080")
    c.headers.update({"Origin": "http://127.0.0.1:8080"})
    return c
