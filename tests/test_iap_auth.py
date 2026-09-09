"""Unit tests for Google Cloud IAP identity parsing and role-based permissions."""

from __future__ import annotations

import os
from fastapi.testclient import TestClient

from openkb.api import create_app


def _client(monkeypatch, admin_emails: str | None = None, token: str | None = None) -> TestClient:
    if admin_emails is not None:
        monkeypatch.setenv("OPENKB_ADMIN_EMAILS", admin_emails)
    else:
        monkeypatch.delenv("OPENKB_ADMIN_EMAILS", raising=False)

    if token is not None:
        monkeypatch.setenv("OPENKB_API_TOKEN", token)
    else:
        monkeypatch.delenv("OPENKB_API_TOKEN", raising=False)

    return TestClient(create_app())


def test_whoami_unauthenticated_local_dev(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    client = _client(monkeypatch, admin_emails=None, token=None)

    resp = client.get("/api/v1/auth/whoami")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] is None
    assert data["is_admin"] is True
    assert data["authenticated"] is False
    assert data["admin_enforced"] is False


def test_whoami_with_iap_headers(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    client = _client(monkeypatch, admin_emails="jeromerajan@google.com,lead@google.com")

    # Admin user via IAP header
    resp = client.get(
        "/api/v1/auth/whoami",
        headers={"x-goog-authenticated-user-email": "accounts.google.com:jeromerajan@google.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "jeromerajan@google.com"
    assert data["is_admin"] is True
    assert data["authenticated"] is True
    assert data["admin_enforced"] is True

    # Non-admin colleague via IAP header
    resp = client.get(
        "/api/v1/auth/whoami",
        headers={"x-goog-authenticated-user-email": "accounts.google.com:colleague@google.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "colleague@google.com"
    assert data["is_admin"] is False
    assert data["authenticated"] is True


def test_read_endpoints_allowed_for_colleague(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    client = _client(monkeypatch, admin_emails="jeromerajan@google.com")
    colleague_headers = {
        "x-goog-authenticated-user-email": "accounts.google.com:colleague@google.com"
    }

    # Meta
    resp = client.get("/api/v1/meta", headers=colleague_headers)
    assert resp.status_code == 200

    # List KBs
    resp = client.get("/api/v1/kbs", headers=colleague_headers)
    assert resp.status_code == 200

    # Config get
    resp = client.get("/api/v1/config", headers=colleague_headers)
    assert resp.status_code == 200


def test_write_endpoints_forbidden_for_colleague(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    client = _client(monkeypatch, admin_emails="jeromerajan@google.com")
    colleague_headers = {
        "x-goog-authenticated-user-email": "accounts.google.com:colleague@google.com"
    }

    # Add (upload)
    resp = client.post("/api/v1/add", data={"kb": "test-kb"}, headers=colleague_headers)
    assert resp.status_code == 403
    assert "Forbidden" in resp.json()["detail"]

    # Remove
    resp = client.post(
        "/api/v1/remove",
        json={"kb": "test-kb", "identifier": "doc1"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # Recompile
    resp = client.post(
        "/api/v1/recompile",
        json={"kb": "test-kb", "all_docs": True},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # Init
    resp = client.post(
        "/api/v1/init",
        json={"kb": "new-kb"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # Config patch
    resp = client.patch(
        "/api/v1/config",
        json={"model": "vertex_ai/gemini-2.5-flash"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # Page edit / delete
    resp = client.put(
        "/api/v1/page",
        json={"kb": "test-kb", "path": "test", "content": "edit"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/v1/page/delete",
        json={"kb": "test-kb", "path": "test"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # KB delete
    resp = client.post(
        "/api/v1/kb/delete",
        json={"kb": "test-kb", "confirm_name": "test-kb"},
        headers=colleague_headers,
    )
    assert resp.status_code == 403

    # Lint fix (mutation) vs Lint report (read-only)
    resp = client.post(
        "/api/v1/lint",
        json={"kb": "test-kb", "fix": True},
        headers=colleague_headers,
    )
    assert resp.status_code == 403


def test_write_endpoints_allowed_for_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    kb_dir = tmp_path / "test-kb"
    (kb_dir / ".openkb").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki").mkdir(parents=True, exist_ok=True)

    client = _client(monkeypatch, admin_emails="jeromerajan@google.com")
    admin_headers = {
        "x-goog-authenticated-user-email": "accounts.google.com:jeromerajan@google.com"
    }

    # Calling /add with admin header passes auth and reaches file validation (400 No files uploaded)
    resp = client.post("/api/v1/add", data={"kb": "test-kb"}, headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No files uploaded."


def test_write_allowed_with_bearer_token_override(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    kb_dir = tmp_path / "test-kb"
    (kb_dir / ".openkb").mkdir(parents=True, exist_ok=True)
    (kb_dir / "wiki").mkdir(parents=True, exist_ok=True)

    client = _client(monkeypatch, admin_emails="jeromerajan@google.com", token="supersecret")
    token_headers = {"Authorization": "Bearer supersecret"}

    resp = client.post("/api/v1/add", data={"kb": "test-kb"}, headers=token_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "No files uploaded."


def test_missing_identity_when_admin_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENKB_KB_ROOT", str(tmp_path))
    client = _client(monkeypatch, admin_emails="jeromerajan@google.com")

    # Anonymous request without IAP header or token
    resp = client.post("/api/v1/add", data={"kb": "test-kb"})
    assert resp.status_code == 401
