"""Document metadata handling for OpenKB.

Supports:
- Autogeneration of dates (Drive modifiedTime or today) and tags (file type, keywords)
  when not provided by the user.
- Deriving clean snapshot filenames (e.g. <name>-YYYY-MM-DD.ext).
- Persisting and consuming inbound metadata across upload/URL boundaries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def autogenerate_metadata(
    filename: str,
    *,
    file_date: str | None = None,
    tags: list[str] | None = None,
    source_modified_time: str | None = None,
    mime_type: str | None = None,
) -> tuple[str, list[str]]:
    """Determine effective date and tags, autogenerating if omitted or blank."""
    # 1. Effective date
    if file_date and file_date.strip():
        eff_date = file_date.strip()
    elif source_modified_time and len(source_modified_time) >= 10:
        eff_date = source_modified_time[:10]
    else:
        eff_date = datetime.now().strftime("%Y-%m-%d")

    # 2. Effective tags
    if tags and len(tags) > 0:
        eff_tags = [t.strip().lstrip("#") for t in tags if t.strip()]
    else:
        eff_tags = []
        ext = Path(filename).suffix.lower()
        if ext in (".xlsx", ".xls", ".csv") or (mime_type and "spreadsheet" in mime_type):
            eff_tags.append("spreadsheet")
        elif ext in (".docx", ".doc") or (mime_type and "document" in mime_type):
            eff_tags.append("document")
        elif ext in (".pptx", ".ppt") or (mime_type and "presentation" in mime_type):
            eff_tags.append("presentation")
        elif ext == ".pdf" or (mime_type and "pdf" in mime_type):
            eff_tags.append("pdf")
        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            eff_tags.append("image")

        if mime_type and "google-apps" in mime_type:
            eff_tags.append("google-drive")

        # Extract useful domain keywords from stem
        stem_lower = Path(filename).stem.lower().replace("-", " ").replace("_", " ")
        for kw in ("burndown", "planning", "standup", "architecture", "report", "roadmap", "budget"):
            if kw in stem_lower and kw not in eff_tags:
                eff_tags.append(kw)

        if not eff_tags:
            eff_tags = ["document"]

    return eff_date, eff_tags


def derive_snapshot_filename(base_name: str, effective_date: str, raw_dir: Path) -> str:
    """Derive a clean snapshot filename: <stem>-<effective_date><ext>.

    If <stem>-<effective_date><ext> already exists in raw_dir, appends
    -v2, -v3, etc. to prevent silent overwrite of historical snapshots.
    """
    path = Path(base_name)
    stem = path.stem
    ext = path.suffix

    candidate = f"{stem}-{effective_date}{ext}"
    if not (raw_dir / candidate).exists():
        return candidate

    for v in range(2, 10_000):
        cand = f"{stem}-{effective_date}-v{v}{ext}"
        if not (raw_dir / cand).exists():
            return cand

    import uuid
    return f"{stem}-{effective_date}-{uuid.uuid4().hex[:6]}{ext}"


def save_inbound_metadata(
    kb_dir: Path,
    filename: str,
    *,
    date: str | None = None,
    tags: list[str] | None = None,
    snapshot: bool = False,
    mode: str = "update",
) -> None:
    """Save metadata into .openkb/inbound_meta/<filename>.json for pickup by ingest pipeline."""
    meta_dir = kb_dir / ".openkb" / "inbound_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_file = meta_dir / f"{filename}.json"
    data = {
        "date": date,
        "tags": tags or [],
        "snapshot": snapshot,
        "mode": mode,
    }
    meta_file.write_text(json.dumps(data), encoding="utf-8")


def consume_inbound_metadata(kb_dir: Path, filename: str) -> dict[str, Any]:
    """Retrieve and delete metadata for filename from .openkb/inbound_meta/."""
    meta_file = kb_dir / ".openkb" / "inbound_meta" / f"{filename}.json"
    if not meta_file.exists():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to parse inbound metadata for %s: %s", filename, exc)
        return {}
    finally:
        meta_file.unlink(missing_ok=True)
