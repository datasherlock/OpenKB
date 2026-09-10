"""Tests for openkb.api_url_router (POST /api/v1/add-url)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from openkb.api import create_app
from openkb.api_models import AddFileItem


@pytest.fixture
def test_app(tmp_path):
    kbs_root = tmp_path / "kbs"
    kbs_root.mkdir()
    kb_dir = kbs_root / "test-kb"
    kb_dir.mkdir()
    (kb_dir / "raw").mkdir()
    (kb_dir / "wiki").mkdir()
    (kb_dir / ".openkb").mkdir()
    (kb_dir / "config.yaml").write_text("model: gpt-4o-mini\n", encoding="utf-8")

    with patch.dict("os.environ", {"OPENKB_KB_ROOT": str(kbs_root)}):
        app = create_app()
        yield app, kb_dir


def test_add_url_endpoint_success(test_app, tmp_path):
    app, kb_dir = test_app
    client = TestClient(app)

    fake_file = tmp_path / "downloaded.md"
    fake_file.write_text("# Hello World\n", encoding="utf-8")

    mock_item = AddFileItem(
        original_name="downloaded.md",
        saved_path=str(fake_file),
        status="added",
        message="Added: downloaded.md",
    )

    with (
        patch("openkb.api_url_router.fetch_url_to_raw", return_value=fake_file),
        patch("openkb.api_url_router._add_saved_file", new_callable=AsyncMock, return_value=mock_item),
    ):
        res = client.post(
            "/api/v1/add-url",
            json={"kb": "test-kb", "url": "https://docs.google.com/document/d/doc123/edit"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["kb"] == "test-kb"
        assert data["added_count"] == 1
        assert len(data["files"]) == 1
        assert data["files"][0]["original_name"] == "downloaded.md"
        assert data["files"][0]["status"] == "added"


def test_add_url_endpoint_fetch_failed(test_app):
    app, kb_dir = test_app
    client = TestClient(app)

    with patch("openkb.api_url_router.fetch_url_to_raw", return_value=None):
        res = client.post(
            "/api/v1/add-url",
            json={"kb": "test-kb", "url": "https://example.com/missing.pdf"},
        )
        assert res.status_code == 400
        assert "Failed to fetch content from URL" in res.json()["detail"]


def test_add_url_endpoint_fetch_exception(test_app):
    app, kb_dir = test_app
    client = TestClient(app)

    with patch("openkb.api_url_router.fetch_url_to_raw", side_effect=RuntimeError("Network timeout")):
        res = client.post(
            "/api/v1/add-url",
            json={"kb": "test-kb", "url": "https://example.com/broken"},
        )
        assert res.status_code == 400
        assert "Network timeout" in res.json()["detail"]
