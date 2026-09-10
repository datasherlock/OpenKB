"""URL ingestion REST endpoints (POST /api/v1/add-url).

Supports ingesting remote URLs, Google Docs, Google Sheets, Google Slides,
and Google Drive files into a knowledge base.

An APIRouter sibling of api_documents_router.py / api_pages_router.py so
api.py and api_helpers.py stay under the per-file line gate.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from openkb.api_auth import require_write_permission
from openkb.api_helpers import _add_saved_file, _resolve_kb, _summarize_add_results
from openkb.api_models import AddResponse, AddUrlRequest
from openkb.url_ingest import fetch_url_to_raw

logger = logging.getLogger("openkb.api_url")

url_router = APIRouter()


@url_router.post("/api/v1/add-url", response_model=AddResponse)
async def add_url_endpoint(
    request: AddUrlRequest,
    _: None = Depends(require_write_permission),
) -> AddResponse:
    """Ingest a web URL or Google Drive link into the knowledge base."""
    kb_dir = _resolve_kb(request.kb)

    # Pre-add sync hook: pull remote changes if auto_pull is enabled
    try:
        from openkb.cloud_sync import run_sync_hook
        run_sync_hook(kb_dir, "pull")
    except Exception as exc:
        logger.warning("Pre-add cloud sync failed: %s", exc)

    try:
        fetched = await run_in_threadpool(fetch_url_to_raw, request.url, kb_dir)
    except Exception as exc:
        logger.exception("Failed to fetch URL %s: %s", request.url, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Could not fetch document from URL: {exc}",
        ) from exc

    if fetched is None:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch content from URL: {request.url}. Verify the link is accessible and properly formatted.",
        )

    item = await _add_saved_file(kb_dir, fetched, fetched.name)

    # Post-add sync hook: push local changes if auto_push is enabled
    try:
        from openkb.cloud_sync import run_sync_hook
        run_sync_hook(kb_dir, "push")
    except Exception as exc:
        logger.warning("Post-add cloud sync failed: %s", exc)

    return _summarize_add_results(request.kb, [item])
