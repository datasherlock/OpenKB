"""Tests for openkb.gdrive (Google Drive ingestion)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openkb.gdrive import (
    DEFAULT_SERVICE_ACCOUNT,
    extract_gdrive_id,
    fetch_gdrive_file_to_raw,
    get_drive_credentials,
    is_gdrive_url,
)


class TestGdriveUrlDetection:
    def test_google_docs_url(self):
        url = "https://docs.google.com/document/d/12XDBPI8j7v6Hc-0eo36sUwKOE4JY12LhHBNpqkwwb-8/edit?usp=sharing"
        assert is_gdrive_url(url)
        assert extract_gdrive_id(url) == "12XDBPI8j7v6Hc-0eo36sUwKOE4JY12LhHBNpqkwwb-8"

    def test_google_sheets_url(self):
        url = "https://docs.google.com/spreadsheets/d/1XtQYrQ2Z0v8o8nd--Zbc-BdhJbI60lAnl2MGVFju2zE/edit#gid=0"
        assert is_gdrive_url(url)
        assert extract_gdrive_id(url) == "1XtQYrQ2Z0v8o8nd--Zbc-BdhJbI60lAnl2MGVFju2zE"

    def test_google_slides_url(self):
        url = "https://docs.google.com/presentation/d/1a2b3c4d5e6f7g8h9i0j_presentation/edit"
        assert is_gdrive_url(url)
        assert extract_gdrive_id(url) == "1a2b3c4d5e6f7g8h9i0j_presentation"

    def test_google_drive_file_url(self):
        url = "https://drive.google.com/file/d/1a2b3c4d5e6f7g8h9i0j_file_id/view?usp=sharing"
        assert is_gdrive_url(url)
        assert extract_gdrive_id(url) == "1a2b3c4d5e6f7g8h9i0j_file_id"

    def test_google_drive_open_url(self):
        url = "https://drive.google.com/open?id=1a2b3c4d5e6f7g8h9i0j_file_id"
        assert is_gdrive_url(url)
        assert extract_gdrive_id(url) == "1a2b3c4d5e6f7g8h9i0j_file_id"

    def test_bare_drive_id(self):
        fid = "12XDBPI8j7v6Hc-0eo36sUwKOE4JY12LhHBNpqkwwb-8"
        assert extract_gdrive_id(fid) == fid

    def test_non_gdrive_url(self):
        assert not is_gdrive_url("https://example.com/paper.pdf")
        assert not is_gdrive_url("https://github.com/VectifyAI/OpenKB")
        assert extract_gdrive_id("https://example.com/paper.pdf") is None
        assert extract_gdrive_id("short") is None


class TestGdriveCredentials:
    def test_get_drive_credentials_native(self):
        mock_creds = MagicMock()
        mock_creds.service_account_email = "test-sa@project.iam.gserviceaccount.com"
        with patch("google.auth.default", return_value=(mock_creds, "my-proj")):
            creds, identity = get_drive_credentials()
            assert creds == mock_creds
            assert identity == "test-sa@project.iam.gserviceaccount.com"

    def test_get_drive_credentials_fallback_impersonation(self):
        # Native ADC fails refresh, falls back to impersonated credentials
        mock_native = MagicMock()
        mock_native.refresh.side_effect = Exception("insufficient scopes")

        mock_base = MagicMock()
        mock_imp = MagicMock()

        with (
            patch("google.auth.default", side_effect=[(mock_native, "proj"), (mock_base, "proj")]),
            patch("google.auth.impersonated_credentials.Credentials", return_value=mock_imp) as mock_imp_cls,
        ):
            creds, identity = get_drive_credentials()
            assert creds == mock_imp
            assert identity == DEFAULT_SERVICE_ACCOUNT
            mock_imp_cls.assert_called_once()


class TestFetchGdriveFileToRaw:
    @pytest.fixture
    def mock_drive_auth(self):
        mock_creds = MagicMock()
        mock_creds.token = "fake-token"
        with patch("openkb.gdrive.get_drive_credentials", return_value=(mock_creds, "mock-sa")):
            yield mock_creds

    def test_fetch_google_doc_exports_docx(self, tmp_path, mock_drive_auth):
        meta_payload = json.dumps({
            "id": "doc123",
            "name": "Project Proposal",
            "mimeType": "application/vnd.google-apps.document",
        }).encode("utf-8")
        docx_content = b"PK\x03\x04FakeDocxBinary"

        def fake_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
            if "fields=id,name,mimeType" in url:
                resp = MagicMock()
                resp.read.return_value = meta_payload
                resp.__enter__.return_value = resp
                return resp
            elif "/export?" in url and "mimeType=application%2Fvnd.openxmlformats-officedocument.wordprocessingml.document" in url:
                resp = MagicMock()
                resp.read.side_effect = [docx_content, b""]
                resp.__enter__.return_value = resp
                return resp
            raise ValueError(f"Unexpected url: {url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = fetch_gdrive_file_to_raw("https://docs.google.com/document/d/doc123/edit", tmp_path)
            assert res is not None
            assert res.exists()
            assert res.suffix == ".docx"
            assert res.name == "Project-Proposal.docx"
            assert res.read_bytes() == docx_content

    def test_fetch_google_sheet_exports_xlsx(self, tmp_path, mock_drive_auth):
        meta_payload = json.dumps({
            "id": "sheet123",
            "name": "Financials 2026",
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }).encode("utf-8")
        xlsx_content = b"PK\x03\x04FakeXlsxBinary"

        def fake_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
            if "fields=id,name,mimeType" in url:
                resp = MagicMock()
                resp.read.return_value = meta_payload
                resp.__enter__.return_value = resp
                return resp
            elif "/export?" in url and "mimeType=application%2Fvnd.openxmlformats-officedocument.spreadsheetml.sheet" in url:
                resp = MagicMock()
                resp.read.side_effect = [xlsx_content, b""]
                resp.__enter__.return_value = resp
                return resp
            raise ValueError(f"Unexpected url: {url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = fetch_gdrive_file_to_raw("https://docs.google.com/spreadsheets/d/sheet123/edit", tmp_path)
            assert res is not None
            assert res.exists()
            assert res.suffix == ".xlsx"
            assert res.name == "Financials-2026.xlsx"
            assert res.read_bytes() == xlsx_content

    def test_fetch_uploaded_drive_file_media(self, tmp_path, mock_drive_auth):
        meta_payload = json.dumps({
            "id": "pdf123",
            "name": "Research_Paper.pdf",
            "mimeType": "application/pdf",
        }).encode("utf-8")
        pdf_content = b"%PDF-1.4 FakePDF"

        def fake_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
            if "fields=id,name,mimeType" in url:
                resp = MagicMock()
                resp.read.return_value = meta_payload
                resp.__enter__.return_value = resp
                return resp
            elif "alt=media" in url:
                resp = MagicMock()
                resp.read.side_effect = [pdf_content, b""]
                resp.__enter__.return_value = resp
                return resp
            raise ValueError(f"Unexpected url: {url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res = fetch_gdrive_file_to_raw("https://drive.google.com/file/d/pdf123/view", tmp_path)
            assert res is not None
            assert res.exists()
            assert res.suffix == ".pdf"
            assert res.name == "Research_Paper.pdf"
            assert res.read_bytes() == pdf_content

    def test_fetch_http_404_error(self, tmp_path, mock_drive_auth):
        err = urllib.error.HTTPError(
            url="https://www.googleapis.com/drive/v3/files/bad_id",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b"{}"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            res = fetch_gdrive_file_to_raw("https://docs.google.com/document/d/bad_id", tmp_path)
            assert res is None

    def test_fetch_http_403_permission_error(self, tmp_path, mock_drive_auth):
        err = urllib.error.HTTPError(
            url="https://www.googleapis.com/drive/v3/files/forbidden_id",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(b"{}"),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            res = fetch_gdrive_file_to_raw("https://docs.google.com/document/d/forbidden_id", tmp_path)
            assert res is None

    def test_fetch_invalid_url(self, tmp_path):
        res = fetch_gdrive_file_to_raw("not-a-valid-url-or-id", tmp_path)
        assert res is None
