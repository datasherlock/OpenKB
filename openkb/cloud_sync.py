"""Google Cloud Storage (GCS) synchronization for OpenKB.

Enables automated and manual synchronization between a local knowledge base
directory and a remote Google Cloud Storage bucket (e.g. backing Cloud Run).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

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

    return False, f"Unknown sync action: {action}"
