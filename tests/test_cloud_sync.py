"""Tests for OpenKB Google Cloud Storage synchronization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from fastapi.testclient import TestClient

from openkb.api import create_app
from openkb.cli import cli
from openkb.cloud_sync import (
    merge_hashes_data,
    merge_index_content,
    merge_log_content,
    normalize_bucket_uri,
    run_sync_hook,
    sync_kb_bidirectional,
    sync_kb_pull,
    sync_kb_push,
)
from openkb.config import resolve_cloud_sync_config


def test_normalize_bucket_uri():
    assert normalize_bucket_uri("my-bucket") == "gs://my-bucket/"
    assert normalize_bucket_uri("gs://my-bucket") == "gs://my-bucket/"
    assert normalize_bucket_uri("gs://my-bucket/path/") == "gs://my-bucket/path/"
    assert normalize_bucket_uri("  gs://my-bucket/path  ") == "gs://my-bucket/path/"


def test_resolve_cloud_sync_config():
    assert resolve_cloud_sync_config({}) is None
    assert resolve_cloud_sync_config({"cloud_sync": "not-a-dict"}) is None
    assert resolve_cloud_sync_config({"cloud_sync": {}}) is None
    assert resolve_cloud_sync_config({"cloud_sync": {"bucket": ""}}) is None

    cfg = resolve_cloud_sync_config({"cloud_sync": {"bucket": "gs://test-bucket"}})
    assert cfg is not None
    assert cfg["bucket"] == "gs://test-bucket"
    assert cfg["enabled"] is True
    assert cfg["auto_push"] is True
    assert cfg["auto_pull"] is False

    cfg_custom = resolve_cloud_sync_config({
        "cloud_sync": {
            "bucket": "test-b",
            "enabled": False,
            "auto_push": False,
            "auto_pull": True,
        }
    })
    assert cfg_custom == {
        "bucket": "test-b",
        "enabled": False,
        "auto_push": False,
        "auto_pull": True,
    }


def test_sync_kb_push_missing_gcloud(tmp_path):
    with patch("openkb.cloud_sync.resolve_gcloud_bin", return_value=None):
        ok, msg = sync_kb_push(tmp_path, "gs://test-bucket")
        assert not ok
        assert "not found" in msg


def test_sync_kb_push_success(tmp_path):
    with patch("openkb.cloud_sync.resolve_gcloud_bin", return_value="/mock/gcloud"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Copying files..."
        mock_run.return_value = mock_proc

        ok, msg = sync_kb_push(
            tmp_path, "gs://test-bucket", dry_run=True, delete_unmatched=True
        )
        assert ok
        assert "Copying files" in msg
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/mock/gcloud"
        assert cmd[1:3] == ["storage", "rsync"]
        assert cmd[3] == str(tmp_path)
        assert cmd[4] == "gs://test-bucket/"
        assert "--dry-run" in cmd
        assert "--delete-unmatched-destination-objects" in cmd


def test_sync_kb_pull_success(tmp_path):
    with patch("openkb.cloud_sync.resolve_gcloud_bin", return_value="/mock/gcloud"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Pull completed."
        mock_run.return_value = mock_proc

        ok, msg = sync_kb_pull(tmp_path, "gs://test-bucket")
        assert ok
        assert msg == "Pull completed."
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[3] == "gs://test-bucket/"
        assert cmd[4] == str(tmp_path)


def test_run_sync_hook(tmp_path):
    # Missing config returns True (noop)
    ok, msg = run_sync_hook(tmp_path, "push")
    assert ok
    assert "No cloud_sync" in msg

    # With config disabled
    cfg_file = tmp_path / ".openkb" / "config.yaml"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("cloud_sync:\n  enabled: false\n  bucket: gs://b\n", encoding="utf-8")

    ok, msg = run_sync_hook(tmp_path, "push")
    assert ok
    assert "disabled" in msg


def test_cli_sync_command(tmp_path, monkeypatch):
    monkeypatch.setattr("openkb.config.GLOBAL_CONFIG_PATH", tmp_path / "global.yaml")
    monkeypatch.setattr("openkb.config.GLOBAL_CONFIG_DIR", tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        res = runner.invoke(cli, ["sync"])
        assert "No knowledge base found" in res.output

    # KB with no cloud_sync config
    kb_dir = tmp_path / "kb"
    cfg_file = kb_dir / ".openkb" / "config.yaml"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("model: gpt-5.4\n", encoding="utf-8")
    (kb_dir / "wiki").mkdir(parents=True)

    res = runner.invoke(cli, ["--kb-dir", str(kb_dir), "sync"])
    assert "No 'cloud_sync' configured" in res.output

    # KB with cloud_sync config
    cfg_file.write_text("cloud_sync:\n  bucket: gs://my-bucket\n", encoding="utf-8")
    with patch("openkb.cloud_sync.sync_kb_bidirectional", return_value=(True, "Bidirectional sync complete")) as mock_bi:
        res = runner.invoke(cli, ["--kb-dir", str(kb_dir), "sync"])
        assert res.exit_code == 0
        assert "[OK] Sync complete" in res.output
        mock_bi.assert_called_once()

    with patch("openkb.cloud_sync.sync_kb_push", return_value=(True, "Synced 5 files")):
        res = runner.invoke(cli, ["--kb-dir", str(kb_dir), "sync", "--push"])
        assert res.exit_code == 0
        assert "[OK] Push complete" in res.output

    with patch("openkb.cloud_sync.sync_kb_pull", return_value=(True, "Pulled 5 files")):
        res = runner.invoke(cli, ["--kb-dir", str(kb_dir), "sync", "--pull"])
        assert res.exit_code == 0
        assert "[OK] Pull complete" in res.output


def test_merge_hashes_data():
    loc = {
        "h1": {"name": "doc1.pdf", "doc_name": "doc1", "doc_id": "id-1"},
        "h2": {"name": "doc2.pdf", "doc_name": "doc2"},
    }
    rem = {
        "h2": {"name": "doc2.pdf", "doc_name": "doc2", "raw_path": "raw/doc2.pdf"},
        "h3": {"name": "doc3.csv", "doc_name": "doc3"},
    }
    merged = merge_hashes_data(loc, rem)
    assert len(merged) == 3
    assert merged["h1"]["doc_id"] == "id-1"
    assert merged["h2"]["raw_path"] == "raw/doc2.pdf"
    assert merged["h3"]["name"] == "doc3.csv"


def test_merge_log_content():
    loc = """# Operations Log

## [2026-09-10 10:00:00] ingest | doc1.pdf

## [2026-09-10 12:00:00] query | hello
"""
    rem = """# Operations Log

## [2026-09-10 10:00:00] ingest | doc1.pdf

## [2026-09-10 11:00:00] ingest | doc2.pdf
"""
    merged = merge_log_content(loc, rem)
    assert "ingest | doc1.pdf" in merged
    assert "ingest | doc2.pdf" in merged
    assert "query | hello" in merged
    pos1 = merged.index("10:00:00")
    pos2 = merged.index("11:00:00")
    pos3 = merged.index("12:00:00")
    assert pos1 < pos2 < pos3


def test_merge_index_content():
    loc = """# Knowledge Base Index

## Documents
- [[summaries/doc1]] (short) — Doc 1

## Concepts
- [[concepts/c1]] — Concept 1
"""
    rem = """# Knowledge Base Index

## Documents
- [[summaries/doc1]] (short) — Doc 1
- [[summaries/doc2]] (pageindex) — Doc 2

## Concepts
- [[concepts/c2]] — Concept 2
"""
    merged = merge_index_content(loc, rem)
    assert "- [[summaries/doc1]] (short) — Doc 1" in merged
    assert "- [[summaries/doc2]] (pageindex) — Doc 2" in merged
    assert "- [[concepts/c1]] — Concept 1" in merged
    assert "- [[concepts/c2]] — Concept 2" in merged
    assert merged.count("- [[summaries/doc1]]") == 1


def test_sync_kb_bidirectional_flow(tmp_path):
    import json
    kb_dir = tmp_path / "kb"
    (kb_dir / ".openkb").mkdir(parents=True)
    (kb_dir / "wiki").mkdir(parents=True)
    (kb_dir / ".openkb" / "hashes.json").write_text('{"loc_h": {"name": "loc.pdf"}}', encoding="utf-8")
    (kb_dir / "wiki" / "log.md").write_text("# Operations Log\n\n## [2026-09-10 10:00:00] ingest | loc.pdf\n", encoding="utf-8")
    (kb_dir / "wiki" / "index.md").write_text("# Knowledge Base Index\n\n## Documents\n- [[summaries/loc]] (short) — Loc\n", encoding="utf-8")

    def mock_pull(target_kb, bucket, **kwargs):
        (target_kb / ".openkb" / "hashes.json").write_text('{"rem_h": {"name": "rem.pdf"}}', encoding="utf-8")
        (target_kb / "wiki" / "log.md").write_text("# Operations Log\n\n## [2026-09-10 11:00:00] ingest | rem.pdf\n", encoding="utf-8")
        (target_kb / "wiki" / "index.md").write_text("# Knowledge Base Index\n\n## Documents\n- [[summaries/rem]] (short) — Rem\n", encoding="utf-8")
        return True, "Pull success"

    with patch("openkb.cloud_sync.sync_kb_pull", side_effect=mock_pull) as p_pull, \
         patch("openkb.cloud_sync.sync_kb_push", return_value=(True, "Push success")) as p_push:
        ok, msg = sync_kb_bidirectional(kb_dir, "gs://test-bucket")
        assert ok
        p_pull.assert_called_once()
        p_push.assert_called_once()

        merged_hashes = json.loads((kb_dir / ".openkb" / "hashes.json").read_text(encoding="utf-8"))
        assert "loc_h" in merged_hashes
        assert "rem_h" in merged_hashes

        merged_log = (kb_dir / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "loc.pdf" in merged_log
        assert "rem.pdf" in merged_log

        merged_index = (kb_dir / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "- [[summaries/loc]]" in merged_index
        assert "- [[summaries/rem]]" in merged_index


def test_api_sync_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("openkb.config.GLOBAL_CONFIG_PATH", tmp_path / "global.yaml")
    monkeypatch.setattr("openkb.config.GLOBAL_CONFIG_DIR", tmp_path)
    kb_dir = tmp_path / "kb"
    cfg_file = kb_dir / ".openkb" / "config.yaml"
    cfg_file.parent.mkdir(parents=True)
    (kb_dir / "wiki").mkdir(parents=True)
    cfg_file.write_text("cloud_sync:\n  bucket: gs://my-bucket\n", encoding="utf-8")

    monkeypatch.setattr("openkb.api_helpers.resolve_kb_alias", lambda kb: kb_dir)

    app = create_app()
    client = TestClient(app)

    with patch("openkb.api_sync_router.sync_kb_push", return_value=(True, "Push ok")):
        res = client.post("/api/v1/kb/sync?kb=test-kb&action=push")
        assert res.status_code == 200
        assert res.json() == {"status": "ok", "action": "push", "message": "Push ok"}

    with patch("openkb.api_sync_router.sync_kb_pull", return_value=(True, "Pull ok")):
        res = client.post("/api/v1/kb/sync?kb=test-kb&action=pull")
        assert res.status_code == 200
        assert res.json() == {"status": "ok", "action": "pull", "message": "Pull ok"}

    res_invalid = client.post("/api/v1/kb/sync?kb=test-kb&action=invalid")
    assert res_invalid.status_code == 400
