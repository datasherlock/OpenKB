"""Global-config REST endpoints (GET/PATCH /api/v1/config).

An APIRouter (sibling of api_graph.py / api_output.py) so api.py stays under the
per-file line gate (tests/test_file_size.py). Global writes are serialized by
save_global_config's own lock (openkb/config.py), NOT the per-KB mutation lock,
so these endpoints need no create_app closure and extract cleanly.
"""

from __future__ import annotations

from pathlib import Path
import yaml
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from openkb.api_auth import require_read_permission, require_write_permission
from openkb.api_config import apply_global_config_patch, read_global_config
from openkb.api_models import GlobalConfigPatchRequest, GlobalConfigResponse
from openkb.config import registered_kbs, resolve_kb_alias

config_router = APIRouter()


class PromptItem(BaseModel):
    title: str
    prompt: str
    description: str = ""


class KbPromptsResponse(BaseModel):
    prompts: list[PromptItem]


def load_kb_prompts(kb_dir: Path) -> list[PromptItem]:
    """Load preset prompt cards from prompts.yaml or .openkb/config.yaml."""
    candidates = [
        kb_dir / "prompts.yaml",
        kb_dir / "prompts.yml",
        kb_dir / ".openkb" / "prompts.yaml",
        kb_dir / ".openkb" / "config.yaml",
    ]
    raw_data = None
    for cand in candidates:
        if cand.is_file():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data:
                    raw_data = data
                    break
            except Exception:
                continue

    if not raw_data:
        return []

    items = []
    if isinstance(raw_data, list):
        items = raw_data
    elif isinstance(raw_data, dict):
        items = raw_data.get("prompts", [])
        if not isinstance(items, list):
            items = []

    result: list[PromptItem] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            result.append(PromptItem(title=item.strip(), prompt=item.strip()))
        elif isinstance(item, dict):
            prompt = str(item.get("prompt") or item.get("title") or "").strip()
            title = str(item.get("title") or item.get("prompt") or "").strip()
            desc = str(item.get("description") or "").strip()
            if prompt:
                result.append(PromptItem(title=title, prompt=prompt, description=desc))
    return result


@config_router.get("/api/v1/kb/prompts", response_model=KbPromptsResponse)
async def kb_prompts_get(
    kb: str | None = None,
    _: None = Depends(require_read_permission),
) -> KbPromptsResponse:
    """Return preset prompts defined for the given KB or fallback KB."""
    target_dir: Path | None = None
    if kb:
        try:
            target_dir = resolve_kb_alias(kb)
        except Exception:
            target_dir = None
    if target_dir is None or not target_dir.is_dir():
        kbs = registered_kbs()
        if kbs:
            target_dir = kbs[0][1]

    if target_dir and target_dir.is_dir():
        prompts = load_kb_prompts(target_dir)
        return KbPromptsResponse(prompts=prompts)

    return KbPromptsResponse(prompts=[])


@config_router.get("/api/v1/config", response_model=GlobalConfigResponse)
async def global_config_get(
    _: None = Depends(require_read_permission),
) -> GlobalConfigResponse:
    return read_global_config()


@config_router.patch("/api/v1/config", response_model=GlobalConfigResponse)
async def global_config_patch(
    request: GlobalConfigPatchRequest,
    _: None = Depends(require_write_permission),
) -> GlobalConfigResponse:
    # apply_global_config_patch acquires a blocking portalocker flock; run it in
    # a threadpool so the async event loop is not frozen under lock contention
    # (matches the /init endpoint's run_in_threadpool offload in api.py). The
    # read path below holds no lock, so it stays on the event loop.
    await run_in_threadpool(apply_global_config_patch, request)
    return read_global_config()

