"""Bounded single-slot ingest worker.

Ordering is the whole security property here: vectors are STAGED (invisible to
retrieval), then SQLite `commit_chunks_and_ready` runs, and only after it
commits are the staged vectors promoted to `ready`. Any failure or interruption
takes the `fail_ingest` path and discards every staged vector, so there is
never a partial index and a document never becomes `ready` with missing or
orphan vectors.
"""
from __future__ import annotations

import logging
import signal
import time

from . import embeddings
from .chunking import chunk_text
from .errors import NotFound, StateConflict
from .extract import ExtractionFailed, run_isolated_extraction
from .ids import new_id
from .repository import ChunkInput

log = logging.getLogger("ingest")


class IngestWorker:
    def __init__(self, config, repo, vectors, poll_seconds: float = 1.0):
        self.config = config
        self.repo = repo
        self.vectors = vectors
        self.poll_seconds = poll_seconds
        self._stop = False

    def stop(self, *_a) -> None:
        self._stop = True

    # ------------------------------------------------------------------ run
    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        reconciled = self.repo.reconcile_stale_processing()
        if reconciled:
            log.warning("reconciled %d interrupted ingest(s) to failed", reconciled)
        while not self._stop:
            if not self.run_once():
                time.sleep(self.poll_seconds)

    def run_once(self) -> bool:
        """Process at most one queued document. Returns True if work was done."""
        doc = self.repo.next_uploaded_document()
        if doc is None:
            return False
        self.process(doc["account_id"], doc["id"])
        return True

    # -------------------------------------------------------------- process
    def process(self, account_id: str, document_id: str) -> str:
        try:
            doc = self.repo.claim_ingest(account_id, document_id)
        except (NotFound, StateConflict):
            return "skipped"
        generation = int(doc["generation"])
        try:
            source = self.repo.storage_path(account_id, document_id)
            source_format = "pdf" if doc["original_filename"].lower().endswith(".pdf") else "text"
            extracted = run_isolated_extraction(self.config, account_id, document_id, source,
                                                source_format)

            pieces = chunk_text(
                extracted.text,
                int(self.config.section("ingest").get("chunk_tokens", 800)),
                int(self.config.section("ingest").get("chunk_overlap_tokens", 120)),
            )
            if not pieces:
                raise ExtractionFailed("empty_extracted_text")

            model_version = embeddings.model_version(self.config)
            vectors = embeddings.embed_texts(self.config, [p.text for p in pieces])

            chunk_inputs = []
            staged_rows = []
            for piece, vector in zip(pieces, vectors):
                chunk_id = new_id()
                chunk_inputs.append(ChunkInput(
                    ordinal=piece.ordinal, text=piece.text, location_kind="line",
                    location_start=piece.line_start, location_end=piece.line_end,
                    embedding_model=model_version, chunk_id=chunk_id))
                staged_rows.append({"chunk_id": chunk_id, "vector": vector})

            # 1. stage vectors (state='staging' -> invisible to retrieval)
            self.vectors.stage(account_id, document_id, generation, staged_rows)
            # 2. SQLite transaction is the gate
            self.repo.commit_chunks_and_ready(account_id, document_id, generation, chunk_inputs)
            # 3. only now do the vectors become visible
            self.vectors.promote(account_id, document_id, generation)
            log.info("ingest ready document=%s chunks=%d", document_id, len(chunk_inputs))
            return "ready"
        except BaseException as exc:  # includes KeyboardInterrupt / SystemExit
            code = getattr(exc, "code", None) or type(exc).__name__.lower()[:64]
            self._cleanup_failure(account_id, document_id, generation, str(code))
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            log.warning("ingest failed document=%s code=%s", document_id, code)
            return "failed"

    def _cleanup_failure(self, account_id: str, document_id: str, generation: int, code: str) -> None:
        # No partial index may survive: drop every vector for this document.
        try:
            self.vectors.delete_document(account_id, document_id)
        except Exception:  # pragma: no cover
            log.exception("vector cleanup failed")
        try:
            self.repo.fail_ingest(account_id, document_id, code)
        except (NotFound, StateConflict):
            pass
        try:
            work = self.config.work_dir / account_id / f"{document_id}.txt"
            if work.is_file() and not work.is_symlink():
                work.unlink()
        except OSError:  # pragma: no cover
            pass


def main() -> int:  # pragma: no cover - process entrypoint
    from .runtime import build_runtime

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    rt = build_runtime()
    # Warm the pinned model once so the first ingest is not penalised.
    embeddings.load_model(rt.config)
    IngestWorker(rt.config, rt.repo, rt.vectors).run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
