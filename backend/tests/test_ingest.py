"""Ingest worker: isolation of extraction, and the no-partial-index invariant."""
from __future__ import annotations

import secrets
import shutil

import pytest

from backend.app import embeddings
from backend.app.extract import ExtractionFailed, run_isolated_extraction
from backend.app.ingest import IngestWorker

from .conftest import deterministic_vector
from .helpers import make_account

TEXT = "\n\n".join(f"Paragraph {i} about maintenance windows and rotation." for i in range(5))


def _simple_pdf(message: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({message}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return pdf


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="Poppler unavailable")
def test_pdf_is_indexed_and_bad_pdf_fails_safely(runtime, fake_embeddings):
    account = make_account(runtime, "pdf@example.test")
    worker = IngestWorker(runtime.config, runtime.repo, runtime.vectors)
    good = _upload(runtime, account, _simple_pdf("PDF maintenance windows"), "notes.pdf")
    assert worker.process(account, good) == "ready"
    assert "PDF maintenance windows" in runtime.repo.retrieve_ready_chunks(
        account, deterministic_vector("PDF maintenance windows"), 5)[0]["text"]
    bad = _upload(runtime, account, b"%PDF-not-a-document", "bad.pdf")
    assert worker.process(account, bad) == "failed"
    assert runtime.repo.get_document(account, bad)["failure_code"] == "invalid_pdf"


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
