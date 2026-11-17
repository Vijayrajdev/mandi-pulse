"""Tests for ingestion/collect_daily.py: output folders, crash-safe writes and manifests."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from ingestion import collect_daily as cd
from tests.conftest import FAKE_KEY, make_page

RECORDS = [
    {"state": "Keralam", "market": "Mukkom Market", "modal_price": 2200},
    {"state": "Telangana", "market": "RYTHU BAZAR FALAKNUMA", "modal_price": 1800},
    {"state": "Tamil Nadu", "market": "Koyambedu", "modal_price": 3000},
]


def fake_pages(*pages):
    """Patch iter_pages (as used inside collect_daily) to yield the given pages."""
    return mock.patch.object(cd, "iter_pages", return_value=iter(pages))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- dates and folders -------------------------------------------------------------------


def test_today_ist_is_iso_date():
    value = cd.today_ist()
    assert len(value) == 10 and value[4] == "-" and value[7] == "-"


def test_get_output_dir_builds_partition_path_under_data_dir():
    out = cd.get_output_dir("2026-11-10")

    expected = (
        Path(os.environ["DATA_DIR"]) / "raw" / "agmarknet" / "ingest_date=2026-11-10"
    )
    assert out == expected
    assert out.is_dir()


def test_get_output_dir_is_safe_to_call_twice():
    first = cd.get_output_dir("2026-11-10")
    second = cd.get_output_dir("2026-11-10")  # exist_ok=True -> no FileExistsError
    assert first == second


# --- write_records -----------------------------------------------------------------------


def test_write_records_writes_jsonl_and_returns_counts(tmp_path):
    pages = (make_page(RECORDS[:2], total=3), make_page(RECORDS[2:], total=3))
    with fake_pages(*pages):
        counts = cd.write_records(tmp_path)

    assert counts == {
        "api_total": 3,
        "records_received": 3,
        "source_updated_date": "2026-11-10T07:00:00Z",
    }
    assert read_jsonl(tmp_path / "records.jsonl") == RECORDS  # one JSON object per line
    assert not (tmp_path / "records.jsonl.tmp").exists()  # temp file renamed away


def test_write_records_keeps_non_english_text_readable(tmp_path):
    with fake_pages(make_page([{"market": "कोयम्बेडु"}], total=1)):
        cd.write_records(tmp_path)

    text = (tmp_path / "records.jsonl").read_text(encoding="utf-8")
    assert "कोयम्बेडु" in text  # ensure_ascii=False: not क... escapes


def test_crash_mid_write_keeps_old_file_and_leaves_no_tmp(tmp_path):
    old_file = tmp_path / "records.jsonl"
    old_file.write_text("OLD GOOD DATA\n")

    def pages_then_crash():
        yield make_page(RECORDS[:2], total=3)
        raise RuntimeError("API died on page 2")

    with (
        mock.patch.object(cd, "iter_pages", pages_then_crash),
        pytest.raises(RuntimeError, match="page 2"),
    ):
        cd.write_records(tmp_path)

    assert old_file.read_text() == "OLD GOOD DATA\n"  # previous run untouched
    assert not (tmp_path / "records.jsonl.tmp").exists()  # partial file cleaned up


def test_rerun_replaces_previous_file(tmp_path):
    (tmp_path / "records.jsonl").write_text("YESTERDAY'S RUN\n")
    with fake_pages(make_page(RECORDS, total=3)):
        cd.write_records(tmp_path)

    assert read_jsonl(tmp_path / "records.jsonl") == RECORDS


def test_max_pages_stops_early(tmp_path):
    pages = (make_page(RECORDS[:1], total=3), make_page(RECORDS[1:2], total=3))
    with fake_pages(*pages):
        counts = cd.write_records(tmp_path, max_pages=1)

    assert counts["records_received"] == 1
    assert counts["api_total"] == 3


# --- write_manifest ----------------------------------------------------------------------


def test_write_manifest_is_readable_json_with_no_tmp_left(tmp_path):
    cd.write_manifest(tmp_path, {"status": "success", "api_total": 3})

    assert json.loads((tmp_path / "_manifest.json").read_text()) == {
        "status": "success",
        "api_total": 3,
    }
    assert not (tmp_path / "_manifest.json.tmp").exists()


# --- decide_status -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("api_total", "received", "max_pages", "expected"),
    [
        (3, 3, None, "success"),
        (3, 2, None, "count_mismatch"),
        (None, 0, None, "count_mismatch"),
        (3, 1, 1, "partial"),
    ],
)
def test_decide_status(api_total, received, max_pages, expected):
    assert cd.decide_status(api_total, received, max_pages) == expected


# --- main --------------------------------------------------------------------------------


def manifest_for_today() -> dict:
    path = cd.get_output_dir(cd.today_ist()) / "_manifest.json"
    return json.loads(path.read_text())


def test_main_success_writes_records_and_manifest():
    with fake_pages(make_page(RECORDS, total=3)):
        returned = cd.main()

    manifest = manifest_for_today()
    assert returned == manifest
    assert manifest["status"] == "success"
    assert manifest["records_received"] == manifest["api_total"] == 3
    assert manifest["ingest_date"] == cd.today_ist()
    assert manifest["started_at"] <= manifest["finished_at"]
    assert manifest["started_at"].endswith("+00:00")  # timestamps are UTC


def test_main_failure_writes_failed_manifest_and_reraises():
    error = cd.AgmarknetAPIError("Gave up at offset=0 after 5 attempts: ConnectTimeout")
    with (
        mock.patch.object(cd, "write_records", side_effect=error),
        pytest.raises(cd.AgmarknetAPIError),
    ):
        cd.main()

    manifest = manifest_for_today()
    assert manifest["status"] == "failed"
    assert "ConnectTimeout" in manifest["error"]


def test_main_failure_never_stores_unknown_error_messages():
    # Other exceptions' messages may contain the URL (and so the API key).
    leaky = RuntimeError(f"boom https://api.data.gov.in/x?api-key={FAKE_KEY}")
    with (
        mock.patch.object(cd, "write_records", side_effect=leaky),
        pytest.raises(RuntimeError),
    ):
        cd.main()

    manifest = manifest_for_today()
    assert manifest["error"] == "RuntimeError"
    assert FAKE_KEY not in json.dumps(manifest)
