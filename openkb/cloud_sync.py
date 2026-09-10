"""Google Cloud Storage (GCS) synchronization for OpenKB.

Enables automated and manual synchronization between a local knowledge base
directory and a remote Google Cloud Storage bucket (e.g. backing Cloud Run).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("openkb.cloud_sync")

DEFAULT_SYNC_EXCLUDE = (
    r"(\.git/.*|\.venv/.*|venv/.*|.*\.lock$|.*__pycache__/.*|\.DS_Store|"
    r".*\.pytest_cache/.*|node_modules/.*|\.env$)"
)


def resolve_gcloud_bin() -> str | None:
    """Locate the gcloud executable on the host system."""
    env_override = os.environ.get("GCLOUD_BIN")
    if env_override and os.path.isfile(env_override) and os.access(env_override, os.X_OK):
        return env_override

    which_path = shutil.which("gcloud")
    if which_path:
        return which_path

    candidates = [
        os.path.expanduser("~/Downloads/google-cloud-sdk/bin/gcloud"),
        os.path.expanduser("~/google-cloud-sdk/bin/gcloud"),
        "/opt/homebrew/bin/gcloud",
        "/usr/local/bin/gcloud",
        "/usr/bin/gcloud",
    ]
    sdk_root = os.environ.get("GOOGLE_CLOUD_SDK_PATH") or os.environ.get("CLOUDSDK_ROOT_DIR")
    if sdk_root:
        candidates.insert(0, os.path.join(sdk_root, "bin", "gcloud"))

    for cand in candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    return None


def normalize_bucket_uri(bucket: str) -> str:
    """Ensure bucket string has gs:// prefix and trailing slash."""
    b = bucket.strip()
    if not b.startswith("gs://"):
        b = f"gs://{b}"
    if not b.endswith("/"):
        b = f"{b}/"
    return b


def sync_kb_push(
    kb_dir: Path,
    bucket: str,
    *,
    dry_run: bool = False,
    delete_unmatched: bool = False,
    exclude_pattern: str | None = None,
) -> tuple[bool, str]:
    """Push local KB files to GCS bucket using gcloud storage rsync."""
    gcloud = resolve_gcloud_bin()
    if not gcloud:
        msg = "gcloud CLI not found; cannot push to GCS."
        logger.warning(msg)
        return False, msg

    bucket_uri = normalize_bucket_uri(bucket)
    exclude = exclude_pattern or DEFAULT_SYNC_EXCLUDE

    cmd = [
        gcloud,
        "storage",
        "rsync",
        str(kb_dir),
        bucket_uri,
        "--recursive",
        f"-x={exclude}",
    ]
    if delete_unmatched:
        cmd.append("--delete-unmatched-destination-objects")
    if dry_run:
        cmd.append("--dry-run")

    logger.info("Pushing %s to %s...", kb_dir, bucket_uri)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip() or "Sync completed successfully."
            logger.info("Cloud sync push succeeded: %s", out)
            return True, out
        else:
            err = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
            logger.warning("Cloud sync push failed: %s", err)
            return False, err
    except Exception as exc:
        logger.warning("Cloud sync push encountered error: %s", exc)
        return False, str(exc)


def sync_kb_pull(
    kb_dir: Path,
    bucket: str,
    *,
    dry_run: bool = False,
    delete_unmatched: bool = False,
    exclude_pattern: str | None = None,
) -> tuple[bool, str]:
    """Pull remote GCS bucket files into local KB directory."""
    gcloud = resolve_gcloud_bin()
    if not gcloud:
        msg = "gcloud CLI not found; cannot pull from GCS."
        logger.warning(msg)
        return False, msg

    bucket_uri = normalize_bucket_uri(bucket)
    exclude = exclude_pattern or DEFAULT_SYNC_EXCLUDE

    cmd = [
        gcloud,
        "storage",
        "rsync",
        bucket_uri,
        str(kb_dir),
        "--recursive",
        f"-x={exclude}",
    ]
    if delete_unmatched:
        cmd.append("--delete-unmatched-destination-objects")
    if dry_run:
        cmd.append("--dry-run")

    logger.info("Pulling %s into %s...", bucket_uri, kb_dir)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip() or "Sync completed successfully."
            logger.info("Cloud sync pull succeeded: %s", out)
            return True, out
        else:
            err = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
            logger.warning("Cloud sync pull failed: %s", err)
            return False, err
    except Exception as exc:
        logger.warning("Cloud sync pull encountered error: %s", exc)
        return False, str(exc)


_LOG_ENTRY_RE = re.compile(r"^##\s+\[(.*?)\]\s+(.*?)$", re.MULTILINE)


def merge_hashes_data(
    local_hashes: dict[str, Any], remote_hashes: dict[str, Any]
) -> dict[str, Any]:
    """Intelligently merge two hashes.json registries.

    Takes the union of all registered documents. If an entry exists in both,
    combines metadata fields so neither side's attributes (e.g. doc_id, raw_path)
    are discarded.
    """
    merged: dict[str, Any] = {}
    all_keys = set(local_hashes.keys()) | set(remote_hashes.keys())

    for k in all_keys:
        loc = local_hashes.get(k)
        rem = remote_hashes.get(k)
        if loc is None and rem is not None:
            merged[k] = dict(rem)
        elif rem is None and loc is not None:
            merged[k] = dict(loc)
        elif loc is not None and rem is not None:
            combined = dict(rem)
            for field, val in loc.items():
                if val or field not in combined:
                    combined[field] = val
            merged[k] = combined

    return merged


def merge_log_content(local_log: str, remote_log: str) -> str:
    """Merge two Operations Log (log.md) files chronologically without duplicates."""
    def _parse_entries(text: str) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        if not text:
            return entries

        lines = text.splitlines()
        cur_ts = ""
        cur_header = ""
        cur_body: list[str] = []

        for line in lines:
            m = _LOG_ENTRY_RE.match(line)
            if m:
                if cur_ts:
                    entries.append((cur_ts, cur_header, "\n".join(cur_body).strip()))
                cur_ts = m.group(1).strip()
                cur_header = line.strip()
                cur_body = []
            elif cur_ts:
                cur_body.append(line)

        if cur_ts:
            entries.append((cur_ts, cur_header, "\n".join(cur_body).strip()))

        return entries

    local_entries = _parse_entries(local_log)
    remote_entries = _parse_entries(remote_log)

    seen = set()
    combined: list[tuple[str, str, str]] = []
    for entry in local_entries + remote_entries:
        key = (entry[0], entry[1], entry[2])
        if key not in seen:
            seen.add(key)
            combined.append(entry)

    combined.sort(key=lambda x: x[0])

    out = ["# Operations Log\n"]
    for ts, header, body in combined:
        out.append(header)
        if body:
            out.append(body)
        out.append("")

    return "\n".join(out).strip() + "\n"


def merge_index_content(local_index: str, remote_index: str) -> str:
    """Merge two index.md files by section, deduplicating bullet links."""
    if not local_index:
        return remote_index
    if not remote_index:
        return local_index

    def _parse_sections(text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        cur_sec = "__header__"
        sections[cur_sec] = []
        for line in text.splitlines():
            if line.startswith("## "):
                cur_sec = line.strip()
                if cur_sec not in sections:
                    sections[cur_sec] = []
            else:
                sections[cur_sec].append(line)
        return sections

    local_secs = _parse_sections(local_index)
    remote_secs = _parse_sections(remote_index)
    all_sec_keys = list(local_secs.keys())
    for k in remote_secs.keys():
        if k not in all_sec_keys:
            all_sec_keys.append(k)

    merged_lines = []
    for sec in all_sec_keys:
        loc_lines = local_secs.get(sec, [])
        rem_lines = remote_secs.get(sec, [])
        if sec == "__header__":
            lines_to_use = loc_lines if any(l.strip() for l in loc_lines) else rem_lines
            merged_lines.extend([l for l in lines_to_use if l.strip()])
            merged_lines.append("")
            continue

        merged_lines.append(sec)
        seen_links = set()
        sec_output = []
        for line in loc_lines + rem_lines:
            stripped = line.strip()
            if stripped.startswith("- [["):
                link_end = stripped.find("]]")
                if link_end != -1:
                    link_target = stripped[:link_end + 2]
                    if link_target in seen_links:
                        continue
                    seen_links.add(link_target)
            elif stripped == "" and (not sec_output or sec_output[-1] == ""):
                continue
            sec_output.append(line)
        merged_lines.extend([l for l in sec_output if l.strip()])
        merged_lines.append("")

    return "\n".join(merged_lines).rstrip() + "\n"


def sync_kb_bidirectional(
    kb_dir: Path,
    bucket: str,
    *,
    dry_run: bool = False,
    delete_unmatched: bool = False,
    exclude_pattern: str | None = None,
) -> tuple[bool, str]:
    """Safely synchronize local KB and GCS bucket bidirectionally.

    1. Snapshots local .openkb/hashes.json, wiki/log.md, and wiki/index.md.
    2. Pulls remote changes from GCS into local KB.
    3. Merges local and remote hashes.json, log.md, and index.md so no documents or history are clobbered.
    4. Pushes the unified state back to GCS.
    """
    from openkb.locks import atomic_write_text

    hashes_file = kb_dir / ".openkb" / "hashes.json"
    log_file = kb_dir / "wiki" / "log.md"
    index_file = kb_dir / "wiki" / "index.md"

    # 1. Snapshot local metadata
    local_hashes: dict[str, Any] = {}
    if hashes_file.exists():
        try:
            local_hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not parse local hashes.json: %s", exc)

    local_log: str = ""
    if log_file.exists():
        try:
            local_log = log_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not read local log.md: %s", exc)

    local_index: str = ""
    if index_file.exists():
        try:
            local_index = index_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not read local index.md: %s", exc)

    # 2. Pull remote changes
    logger.info("Step 1/3: Pulling remote changes from %s...", bucket)
    pull_ok, pull_msg = sync_kb_pull(
        kb_dir,
        bucket,
        dry_run=dry_run,
        delete_unmatched=False,  # Never delete on pull during bidirectional sync
        exclude_pattern=exclude_pattern,
    )
    if not pull_ok:
        return False, f"Bidirectional sync aborted during pull: {pull_msg}"

    if dry_run:
        push_ok, push_msg = sync_kb_push(
            kb_dir,
            bucket,
            dry_run=True,
            delete_unmatched=delete_unmatched,
            exclude_pattern=exclude_pattern,
        )
        return True, f"[Dry Run] Pull: {pull_msg}\n[Dry Run] Push: {push_msg}"

    # 3. Merge metadata
    remote_hashes: dict[str, Any] = {}
    if hashes_file.exists():
        try:
            remote_hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not parse pulled remote hashes.json: %s", exc)

    merged_hashes = merge_hashes_data(local_hashes, remote_hashes)
    try:
        atomic_write_text(hashes_file, json.dumps(merged_hashes, indent=2) + "\n")
    except Exception as exc:
        logger.warning("Failed to write merged hashes.json: %s", exc)

    remote_log: str = ""
    if log_file.exists():
        try:
            remote_log = log_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not read pulled log.md: %s", exc)

    merged_log = merge_log_content(local_log, remote_log)
    try:
        atomic_write_text(log_file, merged_log)
    except Exception as exc:
        logger.warning("Failed to write merged log.md: %s", exc)

    remote_index: str = ""
    if index_file.exists():
        try:
            remote_index = index_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not read pulled index.md: %s", exc)

    merged_index = merge_index_content(local_index, remote_index)
    try:
        atomic_write_text(index_file, merged_index)
    except Exception as exc:
        logger.warning("Failed to write merged index.md: %s", exc)

    # 4. Push unified state back to GCS
    logger.info("Step 2/3: Pushing merged state to %s...", bucket)
    push_ok, push_msg = sync_kb_push(
        kb_dir,
        bucket,
        dry_run=False,
        delete_unmatched=delete_unmatched,
        exclude_pattern=exclude_pattern,
    )
    if not push_ok:
        return False, f"Bidirectional sync completed pull/merge but push failed: {push_msg}"

    return True, f"Bidirectional sync completed successfully (merged {len(merged_hashes)} documents)."


def run_sync_hook(kb_dir: Path, action: str = "push") -> tuple[bool, str]:
    """Execute pre-configured cloud_sync hook based on KB config.yaml.

    Safe: catches all exceptions and logs without breaking caller.
    """
    try:
        from openkb.config import resolve_effective_config
        config = resolve_effective_config(kb_dir)[0]
    except Exception as exc:
        logger.debug("Failed to load effective config for sync hook: %s", exc)
        return False, f"Failed to load config: {exc}"

    cloud_sync = config.get("cloud_sync")
    if not cloud_sync or not isinstance(cloud_sync, dict):
        return True, "No cloud_sync configuration defined."

    if not cloud_sync.get("enabled", True):
        return True, "cloud_sync is disabled."

    bucket = cloud_sync.get("bucket")
    if not bucket or not isinstance(bucket, str):
        return False, "cloud_sync.bucket must be specified."

    if action == "push":
        if not cloud_sync.get("auto_push", True):
            return True, "auto_push is disabled."
        ok, msg = sync_kb_push(kb_dir, bucket)
        if ok:
            try:
                from openkb.log import append_log
                append_log(kb_dir / "wiki", "cloud_sync_push", f"Synced to {bucket}")
            except Exception:
                pass
        return ok, msg

    elif action == "pull":
        if not cloud_sync.get("auto_pull", False):
            return True, "auto_pull is disabled."
        ok, msg = sync_kb_pull(kb_dir, bucket)
        if ok:
            try:
                from openkb.log import append_log
                append_log(kb_dir / "wiki", "cloud_sync_pull", f"Synced from {bucket}")
            except Exception:
                pass
        return ok, msg

    elif action in ("sync", "bidirectional"):
        ok, msg = sync_kb_bidirectional(kb_dir, bucket)
        if ok:
            try:
                from openkb.log import append_log
                append_log(kb_dir / "wiki", "cloud_sync_bidirectional", f"Synced with {bucket}")
            except Exception:
                pass
        return ok, msg

    return False, f"Unknown sync action: {action}"
