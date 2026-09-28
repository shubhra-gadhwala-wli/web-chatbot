"""R6 HTTP hardening, auth policy and path safety."""
from __future__ import annotations

import pytest

from backend.app import auth
from backend.app.paths import PathSafetyError, safe_child

from .helpers import client, login_cookie, make_account

PASSWORD = "correct horse battery staple"


def test_security_headers_on_every_response(runtime):
    c = client(runtime)
    for response in (c.get("/healthz"), c.get("/api/v1/auth/me")):
        h = response.headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["x-frame-options"] == "DENY"


def test_no_cors_middleware_is_installed(runtime):
    from fastapi.middleware.cors import CORSMiddleware

    from backend.app.api import create_app

    app = create_app(runtime)
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
    c = client(runtime)
    response = c.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cross_origin_state_change_is_rejected(runtime):
    c = client(runtime)
    body = {"email": "csrf@example.test", "password": PASSWORD}
    assert c.post("/api/v1/auth/register", json=body,
                  headers={"Origin": "https://evil.example"}).status_code == 403
    # Missing Origin/Referer is rejected too, not trusted.
    c2 = client(runtime)
    c2.headers.pop("Origin", None)
    assert c2.post("/api/v1/auth/register", json=body, headers={"Origin": ""}).status_code == 403


def test_register_login_logout_rotates_and_revokes(runtime):
    c = client(runtime)
    body = {"email": "user@example.test", "password": PASSWORD}
    registered = c.post("/api/v1/auth/register", json=body)
    assert registered.status_code == 201
    account_id = registered.json()["id"]
    cookie = registered.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("samesite", "SameSite")
    assert "Secure" not in cookie  # plain http locally

    assert c.get("/api/v1/auth/me").json() == {"id": account_id}

    first_token = c.cookies.get("session")
    assert c.post("/api/v1/auth/login", json=body).status_code == 200
    assert c.cookies.get("session") != first_token, "token must rotate on login"
    # The pre-login token was revoked.
    assert runtime.repo.session_by_digest(auth.token_digest(first_token)) is None

    assert c.post("/api/v1/auth/logout").status_code == 204
    c.cookies.clear()
    assert c.get("/api/v1/auth/me").status_code == 401


def test_only_token_digest_is_stored(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "d@example.test", "password": PASSWORD})
    token = c.cookies.get("session")
    rows = runtime.db.conn().execute("SELECT token_digest FROM sessions").fetchall()
    assert rows and all(r["token_digest"] != token for r in rows)
    assert any(r["token_digest"] == auth.token_digest(token) for r in rows)


def test_login_error_is_generic_and_identical_for_unknown_email(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "known@example.test", "password": PASSWORD})
    wrong = c.post("/api/v1/auth/login", json={"email": "known@example.test", "password": "x" * 20})
    unknown = c.post("/api/v1/auth/login", json={"email": "nobody@example.test", "password": "x" * 20})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "unauthenticated"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"] == "Invalid credentials"


def test_password_policy(runtime):
    c = client(runtime)
    assert c.post("/api/v1/auth/register",
                  json={"email": "p@example.test", "password": "short"}).status_code == 400
    assert c.post("/api/v1/auth/register",
                  json={"email": "p@example.test", "password": "a" * 1025}).status_code == 400
    assert c.post("/api/v1/auth/register",
                  json={"email": "p@example.test", "password": "a" * 12}).status_code == 201


def test_login_rate_limit(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "rl@example.test", "password": PASSWORD})
    codes = [c.post("/api/v1/auth/login",
                    json={"email": "rl@example.test", "password": "wrong" * 5}).status_code
             for _ in range(15)]
    assert 429 in codes


def test_path_safety_rejects_traversal_and_symlinks(runtime, tmp_path):
    root = runtime.config.files_dir
    with pytest.raises(PathSafetyError):
        safe_child(root, "..")
    with pytest.raises(PathSafetyError):
        safe_child(root, "../../etc/passwd")
    with pytest.raises(PathSafetyError):
        safe_child(root, "a/b")
    with pytest.raises(PathSafetyError):
        safe_child(root, "not-an-opaque-id")

    from backend.app.ids import new_id
    link = new_id()
    (root / link).symlink_to(tmp_path)
    with pytest.raises(PathSafetyError):
        safe_child(root, link, new_id())


def test_upload_rejects_non_txt_and_non_utf8(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "u@example.test", "password": PASSWORD})
    headers = {"Idempotency-Key": "k" * 20}
    assert c.post("/api/v1/documents", files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")},
                  headers=headers).status_code == 415
    assert c.post("/api/v1/documents", files={"file": ("a.txt", b"\xff\xfe\x00bad", "text/plain")},
                  headers=headers).status_code == 415
    assert c.post("/api/v1/documents", files={"file": ("a.txt", b"", "text/plain")},
                  headers=headers).status_code == 400
    assert c.post("/api/v1/documents", files={"file": ("a.txt", b"hello", "text/plain")},
                  headers={"Idempotency-Key": "short"}).status_code == 400


def test_upload_is_idempotent_and_uses_opaque_storage(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "i@example.test", "password": PASSWORD})
    headers = {"Idempotency-Key": "idem" * 5}
    first = c.post("/api/v1/documents", files={"file": ("my secrets.txt", b"hello there", "text/plain")},
                   headers=headers)
    second = c.post("/api/v1/documents", files={"file": ("my secrets.txt", b"hello there", "text/plain")},
                    headers=headers)
    assert first.status_code == 201 and first.json()["id"] == second.json()["id"]
    changed = c.post("/api/v1/documents", files={"file": ("other.txt", b"different", "text/plain")},
                     headers=headers)
    assert changed.status_code == 409

    doc_id = first.json()["id"]
    row = runtime.db.conn().execute("SELECT storage_key FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert "my secrets" not in row["storage_key"] and doc_id in row["storage_key"]
    stored = list(runtime.config.files_dir.rglob("*"))
    assert all("secrets" not in p.name for p in stored)


def test_private_file_modes(runtime):
    c = client(runtime)
    c.post("/api/v1/auth/register", json={"email": "m@example.test", "password": PASSWORD})
    c.post("/api/v1/documents", files={"file": ("m.txt", b"content here", "text/plain")},
           headers={"Idempotency-Key": "m" * 20})
    import stat
    assert stat.S_IMODE(runtime.config.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime.config.files_dir.stat().st_mode) == 0o700
    files = [p for p in runtime.config.files_dir.rglob("*") if p.is_file()]
    assert files and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)
