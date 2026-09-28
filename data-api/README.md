# Data & API contract — first slice

This directory is the implementation handoff for WLI-16.  It intentionally
contains no application credentials, filenames, or user data.

- `openapi.yaml` is the versioned HTTP contract for Backend, Web and QA.
- `repository-contract.md` is the account-scoped persistence interface and the
  required retrieval/deletion behavior.
- `alembic/versions/20260925_0001_initial_scoped_schema.py` is the initial
  SQLite Alembic revision.  It has an idempotent upgrade guard and a reversible
  downgrade.  The application must run `upgrade -> downgrade -> upgrade` on a
  synthetic multi-account fixture before release.

All opaque IDs are server-generated 256-bit URL-safe random values.  Account
IDs are always derived from the session; no request or repository method
accepts a client-supplied account scope.
