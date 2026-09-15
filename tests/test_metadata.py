"""Unit tests for metadata autogeneration and snapshot handling."""

from pathlib import Path
from openkb.metadata import (
    autogenerate_metadata,
    derive_snapshot_filename,
    save_inbound_metadata,
    consume_inbound_metadata,
)


def test_autogenerate_metadata_with_user_inputs():
    date, tags = autogenerate_metadata(
        "my-doc.xlsx",
        file_date="2026-09-01",
        tags=["custom-tag", "finance"],
    )
    assert date == "2026-09-01"
    assert tags == ["custom-tag", "finance"]


def test_autogenerate_metadata_blank_fallback():
    date, tags = autogenerate_metadata(
        "planning-burndown-tracker.xlsx",
        file_date=None,
        tags=None,
        source_modified_time="2026-09-15T10:00:00.000Z",
        mime_type="application/vnd.google-apps.spreadsheet",
    )
    assert date == "2026-09-15"
    assert "spreadsheet" in tags
    assert "google-drive" in tags
    assert "burndown" in tags
    assert "planning" in tags


def test_derive_snapshot_filename(tmp_path):
    fn1 = derive_snapshot_filename("report.xlsx", "2026-09-15", tmp_path)
    assert fn1 == "report-2026-09-15.xlsx"

    # Create the file to simulate collision
    (tmp_path / fn1).touch()

    fn2 = derive_snapshot_filename("report.xlsx", "2026-09-15", tmp_path)
    assert fn2 == "report-2026-09-15-v2.xlsx"

    (tmp_path / fn2).touch()
    fn3 = derive_snapshot_filename("report.xlsx", "2026-09-15", tmp_path)
    assert fn3 == "report-2026-09-15-v3.xlsx"


def test_save_and_consume_inbound_metadata(tmp_path):
    save_inbound_metadata(
        tmp_path,
        "doc.pdf",
        date="2026-09-15",
        tags=["alpha", "beta"],
        snapshot=True,
        mode="snapshot",
    )
    meta = consume_inbound_metadata(tmp_path, "doc.pdf")
    assert meta["date"] == "2026-09-15"
    assert meta["tags"] == ["alpha", "beta"]
    assert meta["snapshot"] is True
    assert meta["mode"] == "snapshot"

    # Consuming a second time returns empty since it was consumed/unlinked
    assert consume_inbound_metadata(tmp_path, "doc.pdf") == {}
