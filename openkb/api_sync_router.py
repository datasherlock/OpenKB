"""Cloud sync REST endpoints (POST /api/v1/kb/sync).

An APIRouter sibling of api_config_router.py / api_kbs_router.py so api.py
stays under the per-file line gate (tests/test_file_size.py).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from openkb.api_auth import require_write_permission
from openkb.api_helpers import _resolve_kb
from openkb.cloud_sync import sync_kb_pull, sync_kb_push
from openkb.config import resolve_effective_config

sync_router = APIRouter()


@sync_router.post("/api/v1/kb/sync")
async def kb_sync_endpoint(
    kb: str = Query(...),
    action: str = Query("push"),
    _: None = Depends(require_write_permission),
) -> dict[str, Any]:
    """Synchronize a knowledge base with its configured Google Cloud Storage bucket."""
    kb_dir = _resolve_kb(kb)
    cfg = resolve_effective_config(kb_dir)[0].get("cloud_sync")
    if not cfg or not isinstance(cfg, dict) or not cfg.get("bucket"):
        raise HTTPException(status_code=400, detail="cloud_sync not configured for this KB.")
    bucket = cfg["bucket"]
    if action == "pull":
        ok, msg = sync_kb_pull(kb_dir, bucket)
    elif action == "push":
        ok, msg = sync_kb_push(kb_dir, bucket)
    else:
        raise HTTPException(status_code=400, detail="action must be 'push' or 'pull'")
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"status": "ok", "action": action, "message": msg}
