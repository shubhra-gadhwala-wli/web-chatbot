"""Cross-account isolation: the required checks from repository-contract.md."""
from __future__ import annotations

import json

import pytest

from backend.app import audit
from backend.app.errors import NotFound
from backend.app.ids import new_id

from .conftest import deterministic_vector
from .helpers import client, login_cookie, make_account, ready_document

SECRET_B = "Bravo's private launch codes are 4815162342."
PUBLIC_A = "Alpha keeps a recipe for sourdough bread in this file."


def _setup(runtime):
    a = make_account(runtime, "a@example.test")
    b = make_account(runtime, "b@example.test")
    doc_a, chunks_a = ready_document(runtime, a, "a.txt", PUBLIC_A, deterministic_vector)
    doc_b, chunks_b = ready_document(runtime, b, "b.txt", SECRET_B, deterministic_vector)
    return a, b, doc_a, chunks_a, doc_b, chunks_b


def test_retrieval_never_crosses_accounts_even_when_b_is_nearest(runtime, fake_embeddings):
    a, b, doc_a, chunks_a, doc_b, chunks_b = _setup(runtime)

    # Query is byte-identical to B's chunk, so B's vector is the nearest.
    query = deterministic_vector(SECRET_B)
    unscoped = runtime.vectors.search(b, query, 5)
    assert unscoped and unscoped[0]["chunk_id"] == chunks_b[0], "B must be the nearest vector"

    result = runtime.repo.retrieve_ready_chunks(a, query, 5)
    assert all(r["document_id"] == doc_a for r in result)
    assert all(r["chunk_id"] not in chunks_b for r in result)
    assert SECRET_B not in json.dumps(result)
    # The LanceDB predicate was A-scoped and applied before top-k.
    assert f"account_id = '{a}'" in runtime.vectors.last_where
    assert "state = 'ready'" in runtime.vectors.last_where


def test_foreign_id_and_random_id_return_identical_404_and_one_audit_event(runtime, fake_embeddings):
    a, b, doc_a, _, doc_b, chunks_b = _setup(runtime)
    c = client(runtime)
    c.cookies.update(login_cookie(runtime, a))

    audit.reset()
    foreign = c.get(f"/api/v1/documents/{doc_b}")
    foreign_events = audit.recent("cross_account_denied")

    audit.reset()
    random_id = new_id()
    missing = c.get(f"/api/v1/documents/{random_id}")
    missing_events = audit.recent("cross_account_denied")

    assert foreign.status_code == missing.status_code == 404
    # Byte-identical apart from the per-request id, which is not a leak.
    fb, mb = foreign.json(), missing.json()
    assert fb["error"]["code"] == mb["error"]["code"] == "not_found"
    assert fb["error"]["message"] == mb["error"]["message"]
    del fb["error"]["requestId"], mb["error"]["requestId"]
    assert json.dumps(fb, sort_keys=True) == json.dumps(mb, sort_keys=True)

    assert len(foreign_events) == 1 and len(missing_events) == 1
    event = foreign_events[0]
    assert event["actor_account_id"] == a
    assert event["resource_type"] == "document"
    assert event["opaque_id"] == doc_b
    assert set(event) == {"event", "actor_account_id", "resource_type", "opaque_id",
                          "request_id", "ts"}
    blob = json.dumps(event)
    assert "b.txt" not in blob and SECRET_B not in blob and "/" not in event["opaque_id"]


def test_foreign_chunk_and_conversation_are_not_found(runtime, fake_embeddings):
    a, b, doc_a, _, doc_b, chunks_b = _setup(runtime)
    conv_b = runtime.repo.create_conversation(b, "B private")["id"]
    c = client(runtime)
    c.cookies.update(login_cookie(runtime, a))

    assert c.get(f"/api/v1/documents/{doc_b}/chunks/{chunks_b[0]}").status_code == 404
    assert c.get(f"/api/v1/documents/{doc_a}/chunks/{chunks_b[0]}").status_code == 404
    assert c.get(f"/api/v1/conversations/{conv_b}").status_code == 404
    assert c.get(f"/api/v1/conversations/{conv_b}/messages").status_code == 404

    with pytest.raises(NotFound):
        runtime.repo.get_citation(a, new_id(), chunks_b[0])


def test_delete_is_idempotent_and_leaves_no_vectors(runtime, fake_embeddings):
    a, b, doc_a, _, doc_b, _ = _setup(runtime)
    assert runtime.vectors.count(account_id=a, document_id=doc_a) > 0
    runtime.repo.delete_document(a, doc_a)
    assert runtime.vectors.count(account_id=a, document_id=doc_a) == 0
    # The repository reports the record as gone; the API turns that into the
    # same safe 204 a repeat delete gets, so retry and foreign ID look alike.
    with pytest.raises(NotFound):
        runtime.repo.delete_document(a, doc_a)
    c = client(runtime)
    c.cookies.update(login_cookie(runtime, a))
    assert c.delete(f"/api/v1/documents/{doc_a}").status_code == 204
    assert c.delete(f"/api/v1/documents/{doc_b}").status_code == 204
    assert runtime.vectors.count(account_id=b, document_id=doc_b) > 0
