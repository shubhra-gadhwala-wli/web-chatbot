# Data dictionary and retention

All rows are owned by the local installation's `accounts.id`; account-scoped
tables retain `account_id` even when a foreign key could be inferred, so every
authorization query has an explicit predicate. The application owns all tables.

| Table | Columns / meaning | Retention |
| --- | --- | --- |
| `accounts` | `id` opaque account key; `password_hash` Argon2id only; `created_at`, `disabled_at` lifecycle | Account lifetime; deletion policy is out of v1 scope. |
| `sessions` | opaque `id`; `account_id`; SHA-256 `token_digest`; creation, expiry and revocation times | At most 14 days active; retain revoked metadata only as needed for local security diagnostics. |
| `documents` | opaque `id`, owner, display `original_filename`, generated `storage_key`, content digest/size, state/generation/failure and timestamps/tombstone | Original private file and metadata until owner deletion; deletion removes source and row. |
| `chunks` | opaque ID, owner/document/generation, stable ordinal, canonical extracted text, page/line interval and embedding model | Exists only with its source document; cascades on delete. |
| `conversations` | opaque ID, owner, title, creation/update timestamps | Account lifetime; conversation deletion is out of v1 scope. |
| `messages` | opaque ID, owner/conversation, ordering, role/content/status, client idempotency key and request hash | Conversation lifetime. Failed attempt data is minimal; no model error body. |
| `citations` | opaque ID, owner, assistant message and document/chunk snapshot identifiers | Cascades with source/message. Deleted source must not be resolved. |

LanceDB is **not** a system of record and has no authoritative retention: each
derived vector row contains `account_id`, `document_id`, `chunk_id`,
`generation`, `state`, and vector. It is deleted with its source or rebuilt
from SQLite chunks. Private disk paths are generated keys, never client names.
