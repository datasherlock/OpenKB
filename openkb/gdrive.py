"""Google Drive ingestion module for OpenKB.

Allows downloading Google Docs, Google Sheets, Google Slides, and Google Drive
files into a knowledge base's ``raw/`` directory for automatic conversion and
indexing.

Google Docs are exported as DOCX (converted cleanly to markdown via MarkItDown).
Google Sheets are exported as XLSX (converting all sheets into markdown tables).
Google Slides are exported as PDF.
Regular files stored on Drive are downloaded as binary media.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import click

from openkb.url_ingest import _sanitize_filename, _unique_path

logger = logging.getLogger("openkb.gdrive")

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DEFAULT_SERVICE_ACCOUNT = "121851735443-compute@developer.gserviceaccount.com"
CHUNK_BYTES = 64 * 1024
TIMEOUT_SECONDS = 60

GDRIVE_PATTERNS = [
    re.compile(r"https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"https?://docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"),
    re.compile(r"https?://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)"),
]

EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}


def is_gdrive_url(url: str) -> bool:
    """Return True if ``url`` matches a known Google Drive, Docs, Sheets, or Slides link."""
    if not url or not isinstance(url, str):
        return False
    return any(pattern.search(url) for pattern in GDRIVE_PATTERNS)


def extract_gdrive_id(url_or_id: str) -> str | None:
    """Extract Google Drive file ID from a URL or return the string if already an ID."""
    if not url_or_id or not isinstance(url_or_id, str):
        return None
    url_or_id = url_or_id.strip()
    for pattern in GDRIVE_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    # Check if the string looks like a bare Google Drive ID (typically 25-60 chars alphanumeric/_/-)
    if re.fullmatch(r"[a-zA-Z0-9_-]{25,60}", url_or_id):
        return url_or_id
    return None


def _resolve_target_service_account(kb_dir: Path | None = None) -> str | None:
    """Determine the service account to impersonate if native ADC lacks drive scope."""
    env_sa = os.environ.get("OPENKB_GDRIVE_SERVICE_ACCOUNT") or os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT")
    if env_sa:
        return env_sa.strip()

    if kb_dir:
        try:
            from openkb.config import resolve_effective_config
            cfg = resolve_effective_config(kb_dir)[0]
            gdrive_cfg = cfg.get("gdrive", {})
            if isinstance(gdrive_cfg, dict) and gdrive_cfg.get("service_account"):
                return str(gdrive_cfg["service_account"]).strip()
        except Exception:
            pass

    return DEFAULT_SERVICE_ACCOUNT


def get_drive_credentials(kb_dir: Path | None = None, force_impersonation: bool = False) -> tuple[Any, str]:
    """Obtain valid credentials for the Google Drive API.

    Returns a tuple of (credentials, identity_description).
    1. Direct bearer token via OPENKB_GDRIVE_ACCESS_TOKEN / GDRIVE_ACCESS_TOKEN.
    2. Native application default credentials (if not user credentials).
    3. Service account impersonation fallback.
    """
    env_token = os.environ.get("OPENKB_GDRIVE_ACCESS_TOKEN") or os.environ.get("GDRIVE_ACCESS_TOKEN")
    if env_token:
        class DirectToken:
            def __init__(self, token: str):
                self.token = token.strip()
                self.expired = False

            def refresh(self, request=None):
                pass

        return DirectToken(env_token), "Access Token (Environment Variable)"

    import google.auth
    from google.auth import impersonated_credentials
    from google.auth.transport.requests import Request

    req = Request()
    identity = "Application Default Credentials"

    if not force_impersonation:
        try:
            creds, _ = google.auth.default(scopes=[DRIVE_READONLY_SCOPE])
            # User credentials from 'gcloud auth application-default login' do not carry
            # the drive.readonly scope unless explicitly requested during login.
            is_user_cred = hasattr(creds, "client_id") and not hasattr(creds, "service_account_email")
            if not is_user_cred:
                creds.refresh(req)
                return creds, getattr(creds, "service_account_email", identity)
        except Exception as exc:
            logger.debug("Native ADC with drive.readonly failed: %s; attempting impersonation", exc)

    target_sa = _resolve_target_service_account(kb_dir)
    if not target_sa:
        raise RuntimeError(
            "Could not authenticate with Google Drive API and no impersonation service account is configured."
        )

    try:
        base_creds, _ = google.auth.default()
        base_creds.refresh(req)
        imp_creds = impersonated_credentials.Credentials(
            source_credentials=base_creds,
            target_principal=target_sa,
            target_scopes=[DRIVE_READONLY_SCOPE],
        )
        imp_creds.refresh(req)
        return imp_creds, target_sa
    except Exception as exc:
        raise RuntimeError(
            f"Failed to authenticate against Google Drive API via service account {target_sa}: {exc}"
        ) from exc


def fetch_gdrive_file_to_raw(url_or_id: str, kb_dir: Path) -> Path | None:
    """Download or export a Google Drive file into ``kb_dir / 'raw'``.

    Returns the Path to the saved local file, or None on failure.
    """
    file_id = extract_gdrive_id(url_or_id)
    if not file_id:
        click.echo(f"  [ERROR] Invalid Google Drive URL or File ID: {url_or_id}", err=True)
        return None

    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Fetching Google Drive document (ID: {file_id})...")

    try:
        creds, identity = get_drive_credentials(kb_dir)
    except Exception as exc:
        click.echo(f"  [ERROR] Authentication failed: {exc}", err=True)
        return None

    from google.auth.transport.requests import Request
    if not getattr(creds, "token", None) or getattr(creds, "expired", False):
        try:
            creds.refresh(Request())
        except Exception as exc:
            click.echo(f"  [ERROR] Failed to refresh Drive credentials: {exc}", err=True)
            return None

    auth_header = {"Authorization": f"Bearer {creds.token}"}

    # Step 1: Retrieve metadata
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name,mimeType"
    meta_req = urllib.request.Request(meta_url, headers=auth_header)
    try:
        with urllib.request.urlopen(meta_req, timeout=TIMEOUT_SECONDS) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            click.echo(
                f"  [ERROR] Google Drive file not found or inaccessible (HTTP 404).\n"
                f"  If the file is in a Google Workspace domain (e.g. google.com), corporate\n"
                f"  policy prohibits sharing with external service accounts ('{identity}').\n"
                f"  Resolution options:\n"
                f"    1) Download locally as .docx or .xlsx and run: openkb add <file>\n"
                f"    2) Enable link sharing ('Anyone with the link can view') if allowed\n"
                f"    3) Provide a user access token via OPENKB_GDRIVE_ACCESS_TOKEN",
                err=True,
            )
        elif exc.code == 403:
            click.echo(
                f"  [ERROR] Google Drive permission denied (HTTP 403).\n"
                f"  If corporate policy prohibits sharing with external service accounts ('{identity}'):\n"
                f"    1) Download locally as .docx or .xlsx and run: openkb add <file>\n"
                f"    2) Enable link sharing ('Anyone with the link can view') if allowed\n"
                f"    3) Provide a user access token via OPENKB_GDRIVE_ACCESS_TOKEN",
                err=True,
            )
        else:
            click.echo(f"  [ERROR] Failed to fetch Drive metadata (HTTP {exc.code}): {exc.reason}", err=True)
        return None
    except Exception as exc:
        click.echo(f"  [ERROR] Drive request error: {exc}", err=True)
        return None

    doc_name = meta.get("name") or f"gdrive-{file_id}"
    mime_type = meta.get("mimeType", "")

    # Step 2: Determine whether to export or download raw media
    if mime_type in EXPORT_MIME_TYPES:
        target_mime, ext = EXPORT_MIME_TYPES[mime_type]
        download_url = (
            f"https://www.googleapis.com/drive/v3/files/{file_id}/export?"
            + urllib.parse.urlencode({"mimeType": target_mime})
        )
    else:
        # Pre-existing file uploaded to Drive (PDF, Word doc, etc.)
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        ext = Path(doc_name).suffix
        if not ext:
            ext = ".pdf" if mime_type == "application/pdf" else ""

    sanitized_name = _sanitize_filename(doc_name, ext)
    target = _unique_path(raw_dir / sanitized_name)

    # Step 3: Stream download
    dl_req = urllib.request.Request(download_url, headers=auth_header)
    try:
        with urllib.request.urlopen(dl_req, timeout=TIMEOUT_SECONDS) as resp:
            with open(target, "wb") as out_f:
                while True:
                    chunk = resp.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    out_f.write(chunk)
    except urllib.error.HTTPError as exc:
        target.unlink(missing_ok=True)
        click.echo(f"  [ERROR] Failed to download Drive content (HTTP {exc.code}): {exc.reason}", err=True)
        return None
    except Exception as exc:
        target.unlink(missing_ok=True)
        click.echo(f"  [ERROR] Drive download failed: {exc}", err=True)
        return None

    size_kb = target.stat().st_size // 1024 or 1
    click.echo(f"  Fetched: {doc_name!r} ({mime_type})")
    click.echo(f"  Saved: raw/{target.name} ({size_kb} KB)")
    return target
