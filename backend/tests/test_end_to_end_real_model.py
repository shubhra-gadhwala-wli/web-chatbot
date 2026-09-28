"""End-to-end slice with the REAL pinned local embedding model and the real
LanceDB index. Run with RAG_E2E=1 (requires the model in the local cache).

    RAG_E2E=1 .venv/bin/python -m pytest backend/tests/test_end_to_end_real_model.py -s
"""
from __future__ import annotations

import os

import pytest

from backend.app.answering import AnswerService
from backend.app.ingest import IngestWorker
from backend.app.llm import ChatClient

from .helpers import client, login_cookie, make_account
from .local_openai_server import LocalOpenAIServer

pytestmark = pytest.mark.skipif(os.environ.get("RAG_E2E") != "1",
                                reason="set RAG_E2E=1 to run the real-model end-to-end test")

DOCUMENT = """Operations runbook for the Willow billing service.

The maintenance window for the billing service is 02:00 to 04:00 UTC every Sunday.
During the window, invoices are queued and no charges are issued.

The signing key is rotated every ninety days by the platform on-call engineer.

Escalation goes to the payments duty pager, then to the head of platform.
"""

PASSWORD = "correct horse battery staple"


@pytest.fixture
def real_runtime(runtime, monkeypatch):
    """Real sentence-transformers embeddings; nothing about retrieval mocked."""
    monkeypatch.delenv("RAG_SKIP_MODEL_CHECK", raising=False)
    from backend.app import embeddings
    embeddings.load_model(runtime.config)
    return runtime


def test_real_ingest_answer_and_no_context(real_runtime):
    rt = real_runtime
    c = client(rt)
    account = c.post("/api/v1/auth/register",
                     json={"email": "e2e@example.test", "password": PASSWORD}).json()["id"]

    upload = c.post("/api/v1/documents",
                    files={"file": ("runbook.txt", DOCUMENT.encode(), "text/plain")},
                    headers={"Idempotency-Key": "e2e-upload-key-0001"})
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    assert upload.json()["status"] == "uploaded"

    # Real worker: isolated extraction -> chunking -> real embeddings -> LanceDB
    worker = IngestWorker(rt.config, rt.repo, rt.vectors)
    assert worker.run_once() is True
    assert c.get(f"/api/v1/documents/{document_id}").json()["status"] == "ready"
    assert rt.vectors.count(account_id=account, document_id=document_id, state="ready") > 0

    with LocalOpenAIServer() as server:
        os.environ["RAG_GENERATION_BASE_URL"] = server.base_url
        service = AnswerService(rt.config, rt.repo, ChatClient(rt.config))

        answer, _ = service.answer(account, "When is the maintenance window for billing?")
        print("\nANSWERED:", answer.kind, answer.text, answer.citations)
        assert answer.kind == "answered"
        assert answer.citations and answer.citations[0]["documentId"] == document_id
        assert "02:00" in answer.text

        # Citation handle resolves through the scoped API.
        chunk_id = answer.citations[0]["chunkId"]
        excerpt = c.get(f"/api/v1/documents/{document_id}/chunks/{chunk_id}")
        assert excerpt.status_code == 200 and "maintenance window" in excerpt.json()["text"]

        unrelated, _ = service.answer(account, "How do I tune a harpsichord in a humid climate?")
        print("UNRELATED:", unrelated.kind)
        assert unrelated.kind == "no_relevant_context" and unrelated.citations == []

    del os.environ["RAG_GENERATION_BASE_URL"]


def test_real_forged_handle_from_model_is_rejected(real_runtime):
    rt = real_runtime
    account = make_account(rt, "forge@example.test")
    c = client(rt)
    c.cookies.update(login_cookie(rt, account))
    c.post("/api/v1/documents", files={"file": ("runbook.txt", DOCUMENT.encode(), "text/plain")},
           headers={"Idempotency-Key": "e2e-upload-key-0002"})
    IngestWorker(rt.config, rt.repo, rt.vectors).run_once()

    with LocalOpenAIServer(behaviour="forge") as server:
        os.environ["RAG_GENERATION_BASE_URL"] = server.base_url
        service = AnswerService(rt.config, rt.repo, ChatClient(rt.config))
        answer, persist = service.answer(account, "When is the maintenance window for billing?")
        print("FORGED:", answer.kind, repr(answer.text))
        assert answer.kind == "no_relevant_context"
        assert answer.citations == [] and persist == []
        assert "forged" not in answer.text
    del os.environ["RAG_GENERATION_BASE_URL"]


def test_real_two_account_isolation(real_runtime):
    rt = real_runtime
    from backend.app import embeddings

    a = make_account(rt, "iso-a@example.test")
    b = make_account(rt, "iso-b@example.test")
    ca, cb = client(rt), client(rt)
    ca.cookies.update(login_cookie(rt, a))
    cb.cookies.update(login_cookie(rt, b))
    ca.post("/api/v1/documents", files={"file": ("a.txt", b"Alpha bakes sourdough bread.\n", "text/plain")},
            headers={"Idempotency-Key": "iso-a-key-00000001"})
    cb.post("/api/v1/documents",
            files={"file": ("b.txt", DOCUMENT.encode(), "text/plain")},
            headers={"Idempotency-Key": "iso-b-key-00000001"})
    worker = IngestWorker(rt.config, rt.repo, rt.vectors)
    while worker.run_once():
        pass

    question = "When is the maintenance window for billing?"
    vector = embeddings.embed_query(rt.config, question)
    nearest = rt.vectors.search(b, vector, 5)
    assert nearest, "B must have the nearest real vectors for this question"

    for row in rt.repo.retrieve_ready_chunks(a, vector, 5):
        assert "maintenance window" not in row["text"]
        assert row["document_id"] != nearest[0]["document_id"]
    print("ISOLATION OK: A retrieved", len(rt.repo.retrieve_ready_chunks(a, vector, 5)), "own chunks")
