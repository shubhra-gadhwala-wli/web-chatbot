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
    # DOCUMENT is short enough that the default 800-token chunk target would
    # fold the whole thing into a single chunk, which would let the golden
    # path pass even if cosine ranking across chunks were broken. Force real
    # multi-chunk splitting so retrieval actually has to rank chunks by
    # similarity, not just return "the only chunk there is".
    ingest_section = runtime.config.raw.setdefault("ingest", {})
    ingest_section["chunk_tokens"] = 20
    ingest_section["chunk_overlap_tokens"] = 5
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


def test_real_vector_store_returns_cosine_similarity_not_constant_distance(real_runtime):
    """Regression for WLI-27: VectorStore.search() must apply the cosine metric
    to the LanceDB query, not silently fall back to an unmetriced/L2 distance.

    Isolated at the VectorStore level (bypassing chunking, ingest and the LLM)
    so it fails directly against a LanceDB API mismatch instead of being
    masked by unrelated pipeline behaviour."""
    rt = real_runtime
    from backend.app import embeddings

    near_duplicate = "The maintenance window for the billing service is 02:00 to 04:00 UTC every Sunday."
    unrelated_docs = {
        "doc-bread": "Alpha bakes sourdough bread every weekend at the local farmers market.",
        "doc-report": "The quarterly report shows revenue increased by twelve percent year over year.",
        "doc-cats": "Cats sleep for most of the day and enjoy sunny windowsills in the afternoon.",
    }

    for doc_id, text in unrelated_docs.items():
        vector = embeddings.embed_query(rt.config, text)
        rt.vectors.stage("acct-const-check", doc_id, 1, [{"chunk_id": f"c-{doc_id}", "vector": vector}])
        rt.vectors.promote("acct-const-check", doc_id, 1)

    near_vector = embeddings.embed_query(rt.config, near_duplicate)
    rt.vectors.stage("acct-const-check", "doc-target", 1,
                     [{"chunk_id": "c-target", "vector": near_vector}])
    rt.vectors.promote("acct-const-check", "doc-target", 1)

    query = embeddings.embed_query(rt.config, "When is the maintenance window for billing?")
    results = rt.vectors.search("acct-const-check", query, limit=10)
    by_chunk = {r["chunk_id"]: r["similarity"] for r in results}

    target_similarity = by_chunk["c-target"]
    other_similarities = [s for chunk_id, s in by_chunk.items() if chunk_id != "c-target"]

    assert target_similarity > 0.5, f"near-duplicate similarity too low: {target_similarity}"
    assert len(set(round(s, 6) for s in by_chunk.values())) > 1, (
        "all returned similarities are identical -- the cosine metric is not "
        "affecting the LanceDB distance (constant-distance regression)")
    assert all(target_similarity > s for s in other_similarities), (
        f"near-duplicate ({target_similarity}) did not rank above unrelated docs {other_similarities}")
