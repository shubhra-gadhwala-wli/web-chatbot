# Local RAG voice chatbot

Upload documents, then ask questions about them in a chat UI. Retrieval-augmented
answers run entirely against local services — no data leaves the machine unless
you point the generation endpoint at a remote one yourself.

## Prerequisites

- Python 3.11 (a project virtualenv already lives at `.venv/` in the repo root —
  do not create a new one; if it's missing, ask before recreating it)
- Node.js 20+ and npm, for the `web/` client
- A local OpenAI-compatible chat completion server for generation (e.g.
  [Ollama](https://ollama.com) running `qwen2.5:3b-instruct`, the default model
  in `backend/config.yaml`). The app runs without one, but asking questions will
  fail until it's reachable.

## Setup

1. Copy the backend env template and generate a session secret:

   ```bash
   cp backend/.env.sample backend/.env
   python3 -c "import secrets;print(secrets.token_urlsafe(48))"
   # paste the output as RAG_SESSION_SECRET= in backend/.env
   ```

   `backend/.env` is gitignored. Never put secrets in `backend/config.yaml` —
   that file is committed and holds only non-secret defaults (ADR 2).

2. Install the web client's dependencies:

   ```bash
   cd web && npm install
   ```

## Run locally

Backend (API + ingest worker), from the repo root:

```bash
backend/dev.sh
```

This is idempotent: it creates `./.local-data` (mode 0700), runs migrations,
verifies the pinned embedding model, and starts the API on `127.0.0.1:8080`
plus the background ingest worker. Re-running it is safe.

Web client, in a second terminal:

```bash
cd web && npm run dev
```

Open the printed Vite URL (default `http://localhost:5173`). The dev server
proxies `/api/v1/*` to the backend at `127.0.0.1:8080` so the browser sees a
same-origin API, matching how the built app is served in production (same
FastAPI origin for both UI and API).

## Endpoints

All API routes are under `/api/v1` (see `data-api/openapi.yaml` for the full
contract):

- `POST /api/v1/auth/register`, `/auth/login`, `/auth/logout`, `GET /auth/me`
- `GET/POST /api/v1/documents`, `GET/DELETE /api/v1/documents/{id}`,
  `GET /api/v1/documents/{id}/chunks/{chunkId}`
- `GET/POST /api/v1/conversations`, `GET/PATCH /api/v1/conversations/{id}`,
  `GET/POST /api/v1/conversations/{id}/messages`

The web UI is a single-page app served by Vite in dev (`web/`) and as static
assets from the backend in production; its routes are `/documents` and
`/conversations/:id`.

## Supported uploads

`POST /api/v1/documents` accepts multipart form-data (`file` field) for
`.txt`, `.md`, and `.pdf`, up to 25 MB (`ingest.max_upload_bytes` in
`backend/config.yaml`). `.txt`/`.md` must be valid UTF-8 text. PDF text
extraction runs in an OS-isolated subprocess (`backend/app/extract_child.py`);
a document that fails extraction is stored with `status: "failed"` and a
`failureCode`, surfaced in the UI rather than as a silent error.
PDF support requires the system `poppler-utils` package (`/usr/bin/pdftotext`).
Its parser inherits the child CPU, memory, file, and process limits; the parent
also enforces a wall timeout. No JavaScript or forms are executed. Deployments
must keep Poppler patched because it parses untrusted PDFs. Image-only PDFs
require OCR, which is outside this release.

## Tests

Backend:

```bash
.venv/bin/python3 -m pytest backend/tests/
```

Web:

```bash
cd web && npm test
```

## Configuration

Non-secret defaults live in `backend/config.yaml` (host, port, upload limits,
retrieval and generation settings). Environment variables always override it —
see `backend/.env.sample` for the full list (`RAG_SESSION_SECRET`,
`RAG_GENERATION_API_KEY`, `RAG_HOST`, `RAG_PORT`, `RAG_DATA_DIR`, etc.). Keep
`app.host` at `127.0.0.1` for local-only access; only change it if you
specifically need the backend reachable from outside the machine, and
understand the exposure that implies.
