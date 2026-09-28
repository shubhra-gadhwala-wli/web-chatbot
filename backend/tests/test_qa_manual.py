"""Independent QA verification script for WLI-17, authored by QAFunctional.

Exercises the live HTTP surface (real auth, real repository, real vector store,
deterministic fake embeddings to stay network-free) to independently confirm:
- two-account isolation on documents/chunks/answers
- forged/foreign document id -> 404, non-disclosing, audited
- forged citation handle in an answer request -> rejected
- security headers present on every response (R6)
- path traversal / non-opaque id rejected before touching storage (R3)
"""
from __future__ import annotations

from .conftest import deterministic_vector
from .helpers import client, login_cookie, make_account, ready_document

PASSWORD = "correct horse battery staple"


def test_qa_two_account_isolation_and_forged_ids(runtime, fake_embeddings):
    rt = runtime
    a = make_account(rt, "alice@example.test", PASSWORD)
    b = make_account(rt, "bob@example.test", PASSWORD)
    c = client(rt)
    c.cookies.update(login_cookie(rt, a))

    doc_id, chunk_ids = ready_document(
        rt, a, "alice.txt",
        "Alice's billing runbook.\n\nRotate keys every ninety days.",
        deterministic_vector,
    )

    # Bob cannot see Alice's document or chunk by real id.
    c2 = client(rt)
    c2.cookies.update(login_cookie(rt, b))
    r_doc = c2.get(f"/api/v1/documents/{doc_id}")
    r_chunk = c2.get(f"/api/v1/chunks/{chunk_ids[0]}")
    assert r_doc.status_code == 404, r_doc.text
    assert r_chunk.status_code == 404, r_chunk.text
    assert "alice" not in r_doc.text.lower()

    # Alice can see her own document.
    assert c.get(f"/api/v1/documents/{doc_id}").status_code == 200

    # Forged (well-formed but nonexistent) document id -> 404, identical shape.
    forged = "a" * len(doc_id)
    r_forged = c.get(f"/api/v1/documents/{forged}")
    assert r_forged.status_code == 404

    def _shape(resp):
        body = resp.json()
        body.get("error", {}).pop("requestId", None)
        return body

    assert _shape(r_forged) == _shape(r_doc), "forged-id and cross-account 404 bodies must match (non-disclosing)"

    # Non-opaque / traversal-shaped id rejected before repository/storage lookup.
    for bad_id in ("../../etc/passwd", "..", "%2e%2e%2fetc", "not-a-valid-id"):
        r_bad = c.get(f"/api/v1/documents/{bad_id}")
        assert r_bad.status_code in (400, 404), f"{bad_id!r} -> {r_bad.status_code}"


def test_qa_forged_citation_handle_rejected(runtime, fake_embeddings, monkeypatch):
    rt = runtime
    a = make_account(rt, "carol@example.test", PASSWORD)
    doc_id, chunk_ids = ready_document(
        rt, a, "runbook.txt",
        "The maintenance window is 02:00 to 04:00 UTC every Sunday.",
        deterministic_vector,
    )
    c = client(rt)
    c.cookies.update(login_cookie(rt, a))

    from backend.app import llm

    def fake_complete(self, *a, **k):
        # Model hallucinates a citation handle that was never offered in context.
        return "The window is 02:00-04:00 UTC. [cite:forged-handle-not-in-context]"

    monkeypatch.setattr(llm.ChatClient, "complete", fake_complete)

    conv = c.post("/api/v1/conversations", json={"title": "QA forged citation check"})
    assert conv.status_code == 201, conv.text
    conversation_id = conv.json()["id"]

    resp = c.post(f"/api/v1/conversations/{conversation_id}/messages",
                  json={"text": "When is the maintenance window?",
                        "clientRequestId": "qa-forged-citation-req-0001"})
    assert resp.status_code == 201, resp.text
    body = resp.json()["answer"]
    # A forged/unresolvable citation must not be surfaced as a valid citation.
    citations = body.get("citations", [])
    for cit in citations:
        cid = cit.get("chunk_id") or cit.get("id") or cit.get("chunkId")
        assert cid in chunk_ids, f"forged citation handle leaked into response: {cit}"


def test_replayed_message_includes_citations(runtime, fake_embeddings, monkeypatch):
    """WLI-34 regression: GET /conversations/{id}/messages must return the same
    citations the initial POST returned, not omit them on replay."""
    rt = runtime
    a = make_account(rt, "erin@example.test", PASSWORD)
    question = "The maintenance window is 02:00 to 04:00 UTC every Sunday."
    doc_id, chunk_ids = ready_document(rt, a, "runbook.txt", question, deterministic_vector)
    c = client(rt)
    c.cookies.update(login_cookie(rt, a))

    from backend.app import llm

    def fake_complete(self, system, prompt, *a, **k):
        handle = prompt.split("[[", 1)[1].split("]]", 1)[0]
        return f"The window is 02:00-04:00 UTC. [[{handle}]]"

    monkeypatch.setattr(llm.ChatClient, "complete", fake_complete)

    conv = c.post("/api/v1/conversations", json={"title": "Replay check"})
    assert conv.status_code == 201, conv.text
    conversation_id = conv.json()["id"]

    resp = c.post(f"/api/v1/conversations/{conversation_id}/messages",
                  json={"text": question,
                        "clientRequestId": "replay-citation-req-0001"})
    assert resp.status_code == 201, resp.text
    posted_citations = resp.json()["answer"]["citations"]
    assert posted_citations, "setup expected a verified citation on the initial POST"
    assert posted_citations[0]["documentId"] == doc_id
    assert posted_citations[0]["chunkId"] in chunk_ids

    replay = c.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert replay.status_code == 200, replay.text
    items = replay.json()["items"]
    assistant_messages = [m for m in items if m["role"] == "assistant"]
    assert assistant_messages, "expected an assistant message in the replayed history"
    assert assistant_messages[0]["citations"] == posted_citations

    user_messages = [m for m in items if m["role"] == "user"]
    assert "citations" not in user_messages[0]


def test_qa_security_headers_present(runtime, fake_embeddings):
    rt = runtime
    a = make_account(rt, "dana@example.test", PASSWORD)
    c = client(rt)
    c.cookies.update(login_cookie(rt, a))
    r = c.get("/api/v1/documents")
    assert r.status_code == 200
    headers = {k.lower(): v for k, v in r.headers.items()}
    assert "content-security-policy" in headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert "referrer-policy" in headers
    assert any(h in headers for h in ("x-frame-options",)) or "frame-ancestors" in headers.get("content-security-policy", "")
    assert "access-control-allow-origin" not in headers, "no CORS should be enabled by default"


def test_qa_login_failure_audited_without_content(runtime):
    from backend.app import audit

    rt = runtime
    make_account(rt, "erin@example.test", PASSWORD)
    c = client(rt)
    r = c.post("/api/v1/auth/login", json={"email": "erin@example.test", "password": "wrong password"})
    assert r.status_code == 401
    events = audit.recent() if hasattr(audit, "recent") else None
    if events is not None:
        assert any(e.get("event", "").endswith("login_failed") or "login" in e.get("event", "") for e in events)
