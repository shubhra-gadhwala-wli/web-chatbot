"""WLI-31: a VectorStore handle opened before another process's writes must
still see those writes, because dev.py runs the ingest worker and the API
server as separate OS processes, each with its own long-lived VectorStore."""
from __future__ import annotations

from backend.app.vectors import VectorStore

from .conftest import deterministic_vector


def test_search_sees_writes_committed_by_a_second_table_handle(tmp_path):
    directory = tmp_path / "vectors"

    # Simulates the API server: opens its table handle once, before ingest
    # writes anything, and keeps using that same handle for every request.
    api_side = VectorStore(directory, dimension=384)
    assert api_side.search("acct-1", deterministic_vector("hello world"), limit=5) == []

    # Simulates the ingest worker: a separate process, separate handle,
    # opened against the same on-disk table, writing after the API server
    # already has its handle open.
    ingest_side = VectorStore(directory, dimension=384)
    ingest_side.stage("acct-1", "doc-1", 1, [{
        "chunk_id": "c" * 40,
        "vector": deterministic_vector("hello world"),
    }])
    ingest_side.promote("acct-1", "doc-1", 1)

    # The already-open API-side handle must observe the ingest worker's
    # commits without being reconstructed.
    results = api_side.search("acct-1", deterministic_vector("hello world"), limit=5)
    assert len(results) == 1
    assert results[0]["document_id"] == "doc-1"
    assert results[0]["similarity"] > 0.9

    assert api_side.count(account_id="acct-1", document_id="doc-1", state="ready") == 1


def test_delete_document_sees_writes_committed_by_a_second_table_handle(tmp_path):
    directory = tmp_path / "vectors"

    api_side = VectorStore(directory, dimension=384)
    ingest_side = VectorStore(directory, dimension=384)
    ingest_side.stage("acct-1", "doc-1", 1, [{
        "chunk_id": "c" * 40,
        "vector": deterministic_vector("hello world"),
    }])
    ingest_side.promote("acct-1", "doc-1", 1)

    api_side.delete_document("acct-1", "doc-1")

    assert ingest_side.count(account_id="acct-1", document_id="doc-1") == 0
