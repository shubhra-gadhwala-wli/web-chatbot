"""FastAPI application implementing data-api/openapi.yaml.

Account scope always comes from the session cookie, never from request input.
Missing and foreign resources return a byte-identical 404 body.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, FastAPI, File, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from . import audit, auth
from .answering import AnswerService
from .errors import IdempotencyConflict, NotFound, StateConflict, ValidationError
from .ids import is_opaque_id, new_id
from .llm import CapacityExhausted, ChatClient, ModelTimeout, ModelUnavailable
from .paths import safe_child, write_private_bytes
from .runtime import Runtime, build_runtime, current_request_id

log = logging.getLogger("api")

MAX_UPLOAD = 26214400
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf")
# Extensions whose bytes must decode as UTF-8 text at upload time. PDFs are
# binary and are validated instead by the isolated extraction worker
# (see extract_child.py), which today only decodes text — a PDF upload is
# accepted here and surfaced as a failed document once extraction rejects it.
TEXT_EXTENSIONS = (".txt", ".md")
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def error_body(code: str, message: str, request_id: str | None) -> dict:
    return {"error": {"code": code, "message": message, "requestId": request_id or "req_unknown"}}


def not_found() -> ApiError:
    """The single, identical 404 used for missing AND foreign resources."""
    return ApiError(404, "not_found", "Resource not found")


def _iso(value) -> str:
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value)
    return value.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def document_json(row: dict) -> dict:
    return {
        "id": row["id"],
        "originalFilename": row["original_filename"],
        "byteSize": int(row["byte_size"]),
        "status": row["status"] if row["status"] != "deleting" else "failed",
        "failureCode": row["failure_code"],
        "createdAt": _iso(row["created_at"]),
    }


def message_json(row: dict, citations: list[dict] | None = None) -> dict:
    out = {"id": row["id"], "role": row["role"], "content": row["content"],
           "status": row["status"], "createdAt": _iso(row["created_at"])}
    if row["role"] == "assistant":
        out["citations"] = [{
            "documentId": c["document_id"], "documentName": c["document_name"],
            "chunkId": c["chunk_id"],
            "location": {"kind": c["location_kind"], "start": c["location_start"],
                         "end": c["location_end"]},
        } for c in (citations or [])]
    return out


def conversation_json(row: dict) -> dict:
    return {"id": row["id"], "title": row["title"], "createdAt": _iso(row["created_at"]),
            "updatedAt": _iso(row["updated_at"])}


def create_app(runtime: Runtime | None = None) -> FastAPI:
    rt = runtime or build_runtime()
    config = rt.config
    repo = rt.repo
    auth_cfg = config.section("auth")
    rl_cfg = auth_cfg.get("rate_limit", {})
    limiter = auth.RateLimiter(int(rl_cfg.get("max_attempts", 10)),
                               int(rl_cfg.get("window_seconds", 300)))
    chat = ChatClient(config)
    answers = AnswerService(config, repo, chat)

    # R6: no CORS middleware is installed at all -> same-origin only.
    app = FastAPI(title="Local-first RAG API", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.runtime = rt
    app.state.answers = answers
    app.state.limiter = limiter

    allowed_hosts = {f"{config.host}:{config.port}", f"localhost:{config.port}",
                     f"127.0.0.1:{config.port}", config.host, "localhost", "127.0.0.1"}

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request_id = "req_" + new_id()[:22]
        token = current_request_id.set(request_id)
        request.state.request_id = request_id
        try:
            if request.method in STATE_CHANGING and not auth.origin_is_same(request, allowed_hosts):
                response = JSONResponse(
                    status_code=403,
                    content=error_body("validation_error", "Cross-origin request rejected", request_id))
            else:
                try:
                    response = await call_next(request)
                except ApiError as exc:
                    response = JSONResponse(status_code=exc.status,
                                            content=error_body(exc.code, exc.message, request_id),
                                            headers=exc.headers)
        finally:
            current_request_id.reset(token)
        # R6 hardening headers on every response
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "object-src 'none'; form-action 'self'")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, headers=exc.headers,
                            content=error_body(exc.code, exc.message,
                                               getattr(request.state, "request_id", None)))

    @app.exception_handler(NotFound)
    async def not_found_handler(request: Request, exc: NotFound):
        e = not_found()
        return JSONResponse(status_code=404,
                            content=error_body(e.code, e.message,
                                               getattr(request.state, "request_id", None)))

    @app.exception_handler(StateConflict)
    async def state_conflict_handler(request: Request, exc: StateConflict):
        return JSONResponse(status_code=409,
                            content=error_body("state_conflict", "Resource is not in a valid state",
                                               getattr(request.state, "request_id", None)))

    @app.exception_handler(IdempotencyConflict)
    async def idem_handler(request: Request, exc: IdempotencyConflict):
        return JSONResponse(status_code=409,
                            content=error_body("idempotency_conflict",
                                               "Idempotency key reused with a different payload",
                                               getattr(request.state, "request_id", None)))

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        status = {"file_too_large": 413, "unsupported_media_type": 415}.get(exc.code, 400)
        return JSONResponse(status_code=status,
                            content=error_body(exc.code if exc.code in
                                               ("file_too_large", "unsupported_media_type")
                                               else "validation_error",
                                               "Invalid request",
                                               getattr(request.state, "request_id", None)))

    # ------------------------------------------------------------- sessions
    def issue_session(response: Response, account_id: str) -> None:
        token = auth.new_session_token()
        repo.create_session(account_id, auth.token_digest(token),
                            int(auth_cfg.get("session_ttl_days", 14)))
        response.set_cookie(
            auth.SESSION_COOKIE, token, httponly=True, samesite="lax",
            secure=bool(getattr(response, "_force_secure", False)),
            max_age=int(auth_cfg.get("session_ttl_days", 14)) * 86400, path="/")

    def current_session(request: Request) -> dict:
        token = request.cookies.get(auth.SESSION_COOKIE)
        if not token:
            raise ApiError(401, "unauthenticated", "Authentication required")
        session = repo.session_by_digest(auth.token_digest(token))
        if session is None:
            raise ApiError(401, "unauthenticated", "Authentication required")
        return session

    def account_id_of(request: Request) -> str:
        return current_session(request)["account_id"]

    router = APIRouter(prefix="/api/v1")

    # ----------------------------------------------------------------- auth
    @router.post("/auth/register", status_code=201)
    async def register(request: Request, response: Response):
        body = await _json_body(request)
        ip = request.client.host if request.client else "local"
        if not limiter.check(f"reg:{ip}"):
            raise ApiError(429, "capacity_exhausted", "Too many attempts", {"Retry-After": "60"})
        limiter.record(f"reg:{ip}")
        try:
            email = auth.normalize_email(body.get("email", ""))
            password = auth.validate_password(body.get("password", ""),
                                              int(auth_cfg.get("min_password_length", 12)),
                                              int(auth_cfg.get("max_password_bytes", 1024)))
        except auth.PasswordPolicyError as exc:
            raise ApiError(400, "validation_error", "Invalid email or password") from exc
        try:
            account_id = repo.create_account(email, auth.hasher(config).hash(password))
        except StateConflict:
            raise ApiError(409, "state_conflict", "Account already exists")
        issue_session(_secure_flag(request, response), account_id)
        return {"id": account_id}

    @router.post("/auth/login")
    async def login(request: Request, response: Response):
        body = await _json_body(request)
        ip = request.client.host if request.client else "local"
        email_key = ""
        try:
            email_key = auth.normalize_email(body.get("email", ""))
        except auth.PasswordPolicyError:
            pass
        keys = [f"login:ip:{ip}"] + ([f"login:acct:{email_key}"] if email_key else [])
        if not limiter.check(*keys):
            audit.emit_login_failure("rate_limited", request.state.request_id)
            raise ApiError(429, "capacity_exhausted", "Too many attempts", {"Retry-After": "60"})
        limiter.record(*keys)

        password = body.get("password")
        account = repo.find_account_by_email(email_key) if email_key else None
        # Always run a verification so timing does not reveal account existence.
        ok = auth.verify_password(config, account["password_hash"] if account else None,
                                  password if isinstance(password, str) else "")
        if not ok or (account and account.get("disabled_at")):
            audit.emit_login_failure("invalid_credentials", request.state.request_id)
            raise ApiError(401, "unauthenticated", "Invalid credentials")
        limiter.reset(*keys)
        # Rotate: any prior session for this account is revoked.
        repo.revoke_all_sessions(account["id"])
        issue_session(_secure_flag(request, response), account["id"])
        return {"id": account["id"]}

    @router.post("/auth/logout", status_code=204)
    async def logout(request: Request, response: Response):
        session = current_session(request)
        repo.revoke_session(session["account_id"], session["id"])
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return Response(status_code=204, headers={"set-cookie":
                        f"{auth.SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

    @router.get("/auth/me")
    async def me(request: Request):
        return {"id": account_id_of(request)}

    # ------------------------------------------------------------ documents
    @router.get("/documents")
    async def list_documents(request: Request, cursor: str | None = Query(None),
                             limit: int = Query(25, ge=1, le=100)):
        account_id = account_id_of(request)
        if cursor is not None and not is_opaque_id(cursor):
            raise ApiError(400, "validation_error", "Invalid cursor")
        items, next_cursor = repo.list_documents(account_id, cursor, limit)
        return {"items": [document_json(r) for r in items], "nextCursor": next_cursor}

    @router.post("/documents", status_code=201)
    async def upload_document(request: Request, file: UploadFile = File(...),
                              idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
        account_id = account_id_of(request)
        if not idempotency_key or not (16 <= len(idempotency_key) <= 128):
            raise ApiError(400, "validation_error", "Idempotency-Key header is required")
        filename = (file.filename or "").strip()
        lower_filename = filename.lower()
        if not lower_filename.endswith(ALLOWED_EXTENSIONS):
            raise ApiError(415, "unsupported_media_type", "Only .txt, .md, and .pdf files are supported")
        is_text = lower_filename.endswith(TEXT_EXTENSIONS)

        # Stream with a hard byte ceiling BEFORE any database record exists.
        digest = hashlib.sha256()
        size = 0
        blocks: list[bytes] = []
        while True:
            block = await file.read(1 << 20)
            if not block:
                break
            size += len(block)
            if size > MAX_UPLOAD:
                raise ApiError(413, "file_too_large", "File exceeds 25 MiB")
            digest.update(block)
            blocks.append(block)
        data = b"".join(blocks)
        if not data:
            raise ApiError(400, "validation_error", "File is empty")
        if is_text:
            if b"\x00" in data[:1 << 20]:
                raise ApiError(415, "unsupported_media_type", "File does not look like text")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                raise ApiError(415, "unsupported_media_type", "File is not valid UTF-8 text")

        row = repo.create_upload(account_id, filename, size, digest.hexdigest(), idempotency_key)
        # Path is derived only from generated IDs and is containment-checked.
        account_dir = safe_child(config.files_dir, account_id)
        account_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_private_bytes(repo.storage_path(account_id, row["id"]), data)
        return document_json(row)

    @router.get("/documents/{document_id}")
    async def get_document(request: Request, document_id: str):
        account_id = account_id_of(request)
        _require_opaque(account_id, "document", document_id)
        return document_json(repo.get_document(account_id, document_id))

    @router.delete("/documents/{document_id}", status_code=204)
    async def delete_document(request: Request, document_id: str):
        account_id = account_id_of(request)
        if not is_opaque_id(document_id):
            audit.emit("cross_account_denied", account_id, "document", None,
                       current_request_id.get())
            return Response(status_code=204)
        try:
            repo.delete_document(account_id, document_id)
        except NotFound:
            # Deletion is idempotent and must not disclose whether the document
            # ever existed (or exists for someone else): always 204.
            pass
        return Response(status_code=204)

    @router.get("/documents/{document_id}/chunks/{chunk_id}")
    async def get_chunk(request: Request, document_id: str, chunk_id: str):
        account_id = account_id_of(request)
        _require_opaque(account_id, "document", document_id)
        _require_opaque(account_id, "chunk", chunk_id)
        row = repo.get_chunk(account_id, document_id, chunk_id)
        return {"id": row["id"], "documentId": row["document_id"],
                "location": {"kind": row["location_kind"], "start": row["location_start"],
                             "end": row["location_end"]},
                "text": row["text"]}

    # -------------------------------------------------------- conversations
    @router.get("/conversations")
    async def list_conversations(request: Request, cursor: str | None = Query(None),
                                 limit: int = Query(25, ge=1, le=100)):
        account_id = account_id_of(request)
        items, next_cursor = repo.list_conversations(account_id, cursor, limit)
        return {"items": [conversation_json(r) for r in items], "nextCursor": next_cursor}

    @router.post("/conversations", status_code=201)
    async def create_conversation(request: Request):
        account_id = account_id_of(request)
        body = await _json_body(request)
        title = body.get("title")
        if not isinstance(title, str) or not (1 <= len(title) <= 200):
            raise ApiError(400, "validation_error", "title is required")
        return conversation_json(repo.create_conversation(account_id, title))

    @router.get("/conversations/{conversation_id}")
    async def get_conversation(request: Request, conversation_id: str):
        account_id = account_id_of(request)
        _require_opaque(account_id, "conversation", conversation_id)
        return conversation_json(repo.get_conversation(account_id, conversation_id))

    @router.patch("/conversations/{conversation_id}")
    async def patch_conversation(request: Request, conversation_id: str):
        account_id = account_id_of(request)
        _require_opaque(account_id, "conversation", conversation_id)
        body = await _json_body(request)
        title = body.get("title")
        if not isinstance(title, str) or not (1 <= len(title) <= 200):
            raise ApiError(400, "validation_error", "title is required")
        return conversation_json(repo.rename_conversation(account_id, conversation_id, title))

    @router.get("/conversations/{conversation_id}/messages")
    async def list_messages(request: Request, conversation_id: str,
                            cursor: str | None = Query(None), limit: int = Query(25, ge=1, le=100)):
        account_id = account_id_of(request)
        _require_opaque(account_id, "conversation", conversation_id)
        items, next_cursor = repo.list_messages(account_id, conversation_id, cursor, limit)
        citations_by_message = repo.citations_for_messages(
            account_id, [r["id"] for r in items if r["role"] == "assistant"])
        return {"items": [message_json(r, citations_by_message.get(r["id"])) for r in items],
                "nextCursor": next_cursor}

    @router.post("/conversations/{conversation_id}/messages")
    async def ask(request: Request, conversation_id: str, response: Response):
        account_id = account_id_of(request)
        _require_opaque(account_id, "conversation", conversation_id)
        body = await _json_body(request)
        text = body.get("text")
        client_request_id = body.get("clientRequestId")
        if not isinstance(text, str) or not (1 <= len(text) <= 12000):
            raise ApiError(400, "validation_error", "text is required")
        if not isinstance(client_request_id, str) or not (16 <= len(client_request_id) <= 128):
            raise ApiError(400, "validation_error", "clientRequestId is required")
        repo.get_conversation(account_id, conversation_id)  # scope check

        request_hash = hashlib.sha256(
            json.dumps([conversation_id, text], sort_keys=True).encode()).hexdigest()
        prior = repo.find_message_by_client_request(account_id, client_request_id)
        if prior is not None:
            if prior["request_hash"] != request_hash:
                raise IdempotencyConflict(client_request_id)
            return JSONResponse(status_code=200, content=_prior_response(repo, account_id, prior))

        try:
            answer, persist = answers.answer(account_id, text)
        except CapacityExhausted:
            raise ApiError(429, "capacity_exhausted", "Answer capacity exhausted",
                           {"Retry-After": str(config.section("generation").get("retry_after_seconds", 5))})
        except ModelTimeout:
            raise ApiError(504, "model_timeout", "The configured model timed out")
        except ModelUnavailable:
            raise ApiError(502, "model_unavailable", "The configured model is unavailable")

        user_msg, assistant_msg = repo.persist_answer(
            account_id, conversation_id, text, client_request_id, request_hash,
            answer.text, "completed", persist)
        return JSONResponse(status_code=201, content={
            "message": message_json(user_msg),
            "answer": {"kind": answer.kind, "text": answer.text, "citations": answer.citations},
        })

    # --------------------------------------------------------------- helpers
    def _require_opaque(account_id: str, resource: str, value: str) -> None:
        """A malformed ID gets the same 404 (and the same audit event) as a
        well-formed foreign one, so probing tells the caller nothing."""
        if not is_opaque_id(value):
            audit.emit("cross_account_denied", account_id, resource, None,
                       current_request_id.get())
            raise not_found()

    async def _json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            raise ApiError(400, "validation_error", "Body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "validation_error", "Body must be a JSON object")
        return body

    def _secure_flag(request: Request, response: Response) -> Response:
        # Secure only when the connection is HTTPS (local http stays usable).
        response._force_secure = request.url.scheme == "https"  # type: ignore[attr-defined]
        return response

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    app.include_router(router)
    return app


def _prior_response(repo, account_id: str, prior: dict) -> dict:
    """Idempotent replay of a prior answer attempt."""
    rows, _ = repo.list_messages(account_id, prior["conversation_id"], None, 100)
    assistant = None
    for row in rows:
        if row["sequence"] == prior["sequence"] + 1 and row["role"] == "assistant":
            assistant = row
    citations = repo.citations_for_message(account_id, assistant["id"]) if assistant else []
    kind = "answered" if citations else "no_relevant_context"
    return {
        "message": message_json(prior),
        "answer": {
            "kind": kind,
            "text": assistant["content"] if assistant else "",
            "citations": [{
                "documentId": c["document_id"], "documentName": c["document_name"],
                "chunkId": c["chunk_id"],
                "location": {"kind": c["location_kind"], "start": c["location_start"],
                             "end": c["location_end"]},
            } for c in citations],
        },
    }
