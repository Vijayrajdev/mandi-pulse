"""Tests for ingestion/upload_to_volume.py, using a fake Databricks client (no real upload)."""

import json
from pathlib import Path
from unittest import mock

import pytest

from ingestion import upload_to_volume as up


@pytest.fixture
def run_dir(tmp_path) -> Path:
    """A local day folder with records.jsonl and a successful manifest."""
    (tmp_path / "records.jsonl").write_text('{"market": "Mukkom Market"}\n')
    (tmp_path / "_manifest.json").write_text(
        json.dumps({"status": "success", "records_received": 1})
    )
    return tmp_path


def set_status(run_dir: Path, status: str) -> None:
    (run_dir / "_manifest.json").write_text(json.dumps({"status": status}))


def uploaded_paths(fake_client) -> list[str]:
    return [c.args[0] for c in fake_client.files.upload.call_args_list]


def test_uploads_records_first_and_manifest_last(run_dir):
    fake = mock.MagicMock()  # stands in for WorkspaceClient
    remote = up.upload_run(run_dir, "2026-11-10", client=fake)

    assert remote == "/Volumes/mandi-pulse/mandi/raw/agmarknet/ingest_date=2026-11-10"
    fake.files.create_directory.assert_called_once_with(remote)
    # Manifest last = commit marker: a half-finished upload never looks complete.
    assert uploaded_paths(fake) == [
        f"{remote}/records.jsonl",
        f"{remote}/_manifest.json",
    ]


def test_uploads_with_overwrite_so_reruns_are_safe(run_dir):
    fake = mock.MagicMock()
    up.upload_run(run_dir, "2026-11-10", client=fake)

    for call in fake.files.upload.call_args_list:
        assert call.kwargs["overwrite"] is True


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_refuses_failed_and_partial_runs(run_dir, status):
    set_status(run_dir, status)
    fake = mock.MagicMock()

    with pytest.raises(ValueError, match=status):
        up.upload_run(run_dir, "2026-11-10", client=fake)

    fake.files.upload.assert_not_called()


def test_uploads_count_mismatch_runs(run_dir):
    # Got data, just not exactly api_total - still worth keeping.
    set_status(run_dir, "count_mismatch")
    fake = mock.MagicMock()
    up.upload_run(run_dir, "2026-11-10", client=fake)
    assert fake.files.upload.call_count == 2


def test_missing_manifest_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="run the collector first"):
        up.upload_run(tmp_path, "2026-11-10", client=mock.MagicMock())


def test_missing_records_file_fails_before_uploading_manifest(run_dir):
    (run_dir / "records.jsonl").unlink()
    fake = mock.MagicMock()

    with pytest.raises(FileNotFoundError, match="records.jsonl"):
        up.upload_run(run_dir, "2026-11-10", client=fake)

    fake.files.upload.assert_not_called()


def test_volume_root_can_be_overridden(monkeypatch, run_dir):
    monkeypatch.setenv(
        "DATABRICKS_VOLUME_ROOT", "/Volumes/other/schema/vol/"
    )  # trailing /
    fake = mock.MagicMock()

    remote = up.upload_run(run_dir, "2026-11-10", client=fake)

    assert remote == "/Volumes/other/schema/vol/agmarknet/ingest_date=2026-11-10"
