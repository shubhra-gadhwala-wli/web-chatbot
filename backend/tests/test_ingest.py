"""Ingest worker: isolation of extraction, and the no-partial-index invariant."""
from __future__ import annotations

import secrets

import pytest

from backend.app import embeddings
from backend.app.extract import ExtractionFailed, run_isolated_extraction
from backend.app.ingest import IngestWorker

from .conftest import deterministic_vector
from .helpers import make_account

TEXT = "\n\n".join(f"Paragraph {i} about maintenance windows and rotation." for i in range(5))


def _upload(runtime, account_id, data: bytes, name="notes.txt"):
    doc = runtime.repo.create_upload(account_id, name, len(data), "0" * 64,
                                     secrets.token_urlsafe(16))
    path = runtime.repo.storage_path(account_id, doc["id"])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(data)
    return doc["id"]


def test_extraction_runs_in_isolated_subprocess_and_rejects_bad_input(runtime):
    account = make_account(runtime, "x@example.test")
    good = _upload(runtime, account, TEXT.encode())
    result = run_isolated_extraction(runtime.config, account, good,
                                     runtime.repo.storage_path(account, good))
    assert "maintenance windows" in result.text

    binary = _upload(runtime, account, b"\x00\x01\x02binary")
    with pytest.raises(ExtractionFailed) as exc:
        run_isolated_extraction(runtime.config, account, binary,
                                runtime.repo.storage_path(account, binary))
    assert exc.value.code == "binary_content"

    bad_utf8 = _upload(runtime, account, b"valid then \xff\xfe broken")
    with pytest.raises(ExtractionFailed) as exc:
        run_isolated_extraction(runtime.config, account, bad_utf8,
                                runtime.repo.storage_path(account, bad_utf8))
    assert exc.value.code == "invalid_utf8"


def test_extraction_child_cannot_open_a_socket():
    """The sandbox denies network access before untrusted bytes are parsed."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    child = Path(__file__).resolve().parents[1] / "app" / "extract_child.py"
    probe = (
        "import sys;sys.path.insert(0, %r);"
        "import importlib.util;"
        "spec=importlib.util.spec_from_file_location('c', %r);"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "m._disable_network();"
        "import socket\n"
        "try:\n"
        "    socket.socket()\n"
        "    print('OPEN')\n"
        "except PermissionError:\n"
        "    print('DENIED')\n"
    ) % (str(child.parent), str(child))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert out.stdout.strip() == "DENIED", out


def test_successful_ingest_promotes_vectors_only_after_commit(runtime, fake_embeddings):
    account = make_account(runtime, "ok@example.test")
    doc = _upload(runtime, account, TEXT.encode())
    worker = IngestWorker(runtime.config, runtime.repo, runtime.vectors)
    assert worker.process(account, doc) == "ready"
    assert runtime.repo.get_document(account, doc)["status"] == "ready"
    assert runtime.vectors.count(account_id=account, document_id=doc, state="ready") > 0
    assert runtime.vectors.count(account_id=account, document_id=doc, state="staging") == 0


def test_failure_mid_commit_leaves_no_partial_index(runtime, fake_embeddings, monkeypatch):
    """Simulate a worker crash after vectors are staged but before/while SQLite
    commits: no vectors must survive and the document must land in `failed`."""
    account = make_account(runtime, "boom@example.test")
    doc = _upload(runtime, account, TEXT.encode())
    worker = IngestWorker(runtime.config, runtime.repo, runtime.vectors)

    original = runtime.repo.commit_chunks_and_ready

    def explode(*args, **kwargs):
        # vectors are staged at this point
        assert runtime.vectors.count(account_id=account, document_id=doc, state="staging") > 0
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(runtime.repo, "commit_chunks_and_ready", explode)
    assert worker.process(account, doc) == "failed"
    monkeypatch.setattr(runtime.repo, "commit_chunks_and_ready", original)

    row = runtime.repo.get_document(account, doc)
    assert row["status"] == "failed" and row["failure_code"] == "runtimeerror"
    assert runtime.vectors.count(document_id=doc) == 0, "orphan vectors remain"
    chunks = runtime.db.conn().execute(
        "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?", (doc,)).fetchone()
    assert chunks["n"] == 0, "partially committed chunks remain"


def test_interrupted_processing_is_reconciled_to_failed_not_ready(runtime, fake_embeddings):
    """A killed worker leaves `processing`; startup reconciliation must fail it
    and purge any staged vectors."""
    account = make_account(runtime, "kill@example.test")
    doc = _upload(runtime, account, TEXT.encode())
    runtime.repo.claim_ingest(account, doc)
    runtime.vectors.stage(account, doc, 1, [{"chunk_id": "c" * 40,
                                             "vector": deterministic_vector("x")}])
    assert runtime.vectors.count(document_id=doc) == 1

    assert runtime.repo.reconcile_stale_processing() == 1
    row = runtime.repo.get_document(account, doc)
    assert row["status"] == "failed" and row["failure_code"] == "worker_interrupted"
    assert runtime.vectors.count(document_id=doc) == 0


def test_failed_document_is_never_retrievable(runtime, fake_embeddings):
    account = make_account(runtime, "f@example.test")
    doc = _upload(runtime, account, TEXT.encode())
    runtime.repo.claim_ingest(account, doc)
    runtime.repo.fail_ingest(account, doc, "extraction_failed")
    assert runtime.repo.retrieve_ready_chunks(account, deterministic_vector(TEXT), 5) == []
    assert runtime.repo.has_ready_documents(account) is False
