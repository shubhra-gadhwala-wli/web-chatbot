# Scoped repository contract

`AccountId`, `DocumentId`, `ChunkId`, `ConversationId`, and `MessageId` are
opaque server-generated strings. Every public repository method takes
`account_id` first. A missing record and a record owned by another account both
raise `NotFound`; callers must never distinguish them. Invalid lifecycle use
raises `StateConflict`. A foreign-ID denial emits the `cross_account_denied`
audit hook without document content or filename.

| Method | Contract |
| --- | --- |
| `create_upload(account_id, original_filename, byte_size, content_sha256, idempotency_key)` | Creates `uploaded` document, or returns the prior result for the same account/key and payload. Same key with a changed payload is `IdempotencyConflict`. Storage name is generated from document ID; reject paths/symlinks before write. |
| `claim_ingest(account_id, document_id)` | Atomically changes `uploaded` to `processing`; absent/foreign is `NotFound`; deleted/other state is `StateConflict`. |
| `commit_chunks_and_ready(account_id, document_id, generation, chunks)` | In one SQLite transaction, verifies owner and `processing`, inserts scoped chunks, marks `ready`, and records vector generation. Vector rows are staged before this transition. |
| `fail_ingest(account_id, document_id, failure_code)` | Owner-scoped transition from `uploaded`/`processing` to `failed`; deletion wins if concurrent. |
| `delete_document(account_id, document_id)` | Idempotent: own existing record is tombstoned then file, chunks, citations and vectors are removed; retry returns success. Missing/foreign returns the API's indistinguishable 404. |
| `retrieve_ready_chunks(account_id, query_vector, limit=5)` | First invokes LanceDB with `where="account_id = '<bound account id>' AND state = 'ready'"` **before** `limit`. For each candidate it rechecks SQLite `(account_id, document_id, chunk_id, document.status='ready', document.deleted_at IS NULL, generation)`. It returns only verified chunks. |
| `get_citation(account_id, message_id, chunk_id)` | Joins citation → message → conversation and chunk/document using `account_id` on every joined table. Returns `NotFound` for missing/foreign/deleted source. |

## Typed errors

```text
NotFound(resource, opaque_id)               # API 404, indistinguishable foreign/missing
StateConflict(resource, current_state)      # API 409
IdempotencyConflict(key)                    # API 409
ValidationError(code, field?)               # API 400
```

The audit hook is `audit.emit("cross_account_denied", actor_account_id,
resource_type, opaque_id, request_id)` and must be emitted only after the
authorization predicate fails. It must not include content, vectors, raw file
paths, session tokens, or a boolean that proves resource existence.

## Required isolation checks

1. Create accounts A and B; insert ready documents/chunks/vectors for both.
   `retrieve_ready_chunks(A, ..., 5)` must call LanceDB with account A in its
   predicate and must never return B, even where B is the nearest vector.
2. A's document/chunk/conversation/citation lookup using B's opaque IDs returns
   the exact same `not_found` response as a random opaque ID and writes one
   redacted audit event.
3. Delete A's `processing` document twice; both calls have safe delete
   semantics, no vector remains, and a later worker commit cannot restore it.

## SQLite transaction notes

Use WAL and a short busy timeout.  Keep vector writes staged by document
generation.  SQLite is authoritative: LanceDB is rebuildable derived data and
must never be treated as the authority for ownership or ready state.
