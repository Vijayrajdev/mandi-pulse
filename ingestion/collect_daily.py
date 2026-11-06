"""Daily collector: pulls today's mandi prices and saves them as raw JSONL.

Output: data/raw/agmarknet/ingest_date=YYYY-MM-DD/records.jsonl + _manifest.json

Author: Vijay (github.com/Vijayrajdev)
"""

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Absolute import from the project root. Run with:  python -m ingestion.collect_daily
from ingestion.agmarknet_client import (
    CURRENT_PRICES_RESOURCE_ID,
    AgmarknetAPIError,
    iter_pages,
)

load_dotenv()
logger = logging.getLogger(__name__)

# Mandis, prices and arrival_date are all in Indian time, so partition folders use IST dates.
# (Timestamps such as started_at/finished_at stay in UTC.)
IST = ZoneInfo("Asia/Kolkata")


def utc_now() -> str:
    """Current time in UTC as ISO text, e.g. '2026-11-06T07:15:00+00:00'."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def today_ist() -> str:
    """Return today's date in India as 'YYYY-MM-DD'.

    Not UTC: a 3 AM IST run is still "yesterday" in UTC and would land in
    (and overwrite) the wrong day's folder.
    """
    return datetime.now(IST).date().isoformat()


def get_output_dir(ingest_date: str) -> Path:
    """Return data/raw/agmarknet/ingest_date=<date>/, creating it if needed."""
    # DATA_DIR is the top-level data folder (relative to the project), e.g. "data".
    base_dir = Path(os.getenv("DATA_DIR", "data"))
    out_path = base_dir / "raw" / "agmarknet" / f"ingest_date={ingest_date}"

    # parents=True creates any missing parent folders;
    # exist_ok=True keeps re-runs on the same day safe (idempotent).
    out_path.mkdir(parents=True, exist_ok=True)

    logger.info("Output dir: %s", out_path)
    return out_path


def write_records(output_dir: Path, max_pages: int | None = None) -> dict:
    """Write all records to records.jsonl (via a .tmp file). Return counts for the manifest.

    max_pages is a testing shortcut: stop early instead of downloading every page.
    """
    tmp_path = output_dir / "records.jsonl.tmp"
    final_path = output_dir / "records.jsonl"

    # Filled in from the first page; stay None if the API returns no pages at all.
    api_total = None
    source_updated_date = None
    records_received = 0

    try:
        # Write to a .tmp file first. Until we rename it, records.jsonl is untouched,
        # so a crash halfway never leaves a half-written file that looks complete.
        with open(tmp_path, "w", encoding="utf-8") as f:
            for page_number, page in enumerate(iter_pages(), start=1):
                if page_number == 1:
                    # Page metadata is the same on every page - take it once.
                    api_total = int(page["total"])
                    source_updated_date = page.get("updated_date")

                for record in page["records"]:
                    # JSONL = one JSON object per line. ensure_ascii=False keeps
                    # Hindi/Tamil etc. readable instead of turning them into escape codes.
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    records_received += 1

                if max_pages and page_number >= max_pages:
                    logger.info(
                        "Stopping early after %s page(s) (max_pages)", page_number
                    )
                    break
    except Exception:
        # Something failed mid-download: delete the partial .tmp so nothing half-done
        # is left behind, then re-raise so the caller (and the scheduler) sees the failure.
        tmp_path.unlink(missing_ok=True)
        raise

    # The "commit": only reached if every page succeeded. os.replace is atomic -
    # the file switches from old to new in one step, and overwrites a previous run
    # from the same day (so re-running is safe).
    os.replace(tmp_path, final_path)
    logger.info(
        "Wrote %s records to %s (api total=%s)", records_received, final_path, api_total
    )

    return {
        "api_total": api_total,
        "records_received": records_received,
        "source_updated_date": source_updated_date,
    }


def write_manifest(output_dir: Path, manifest: dict) -> Path:
    """Write _manifest.json (the run's "receipt") next to records.jsonl. Return its path.

    Uses the same .tmp + os.replace trick as write_records, so a crash can never
    leave a half-written manifest behind.
    """
    tmp_path = output_dir / "_manifest.json.tmp"
    final_path = output_dir / "_manifest.json"

    # indent=2 makes it easy for humans to read; sort_keys keeps the field order
    # stable between runs, so two manifests are easy to compare.
    tmp_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, final_path)

    logger.info("Wrote manifest to %s (status=%s)", final_path, manifest.get("status"))
    return final_path


def decide_status(
    api_total: int | None, records_received: int, max_pages: int | None
) -> str:
    """Turn the counts into a status for the manifest."""
    if max_pages:
        # Test run that stopped early - fewer records than api_total is expected.
        return "partial"
    if api_total is not None and records_received == api_total:
        return "success"
    # Got data, but not exactly what the API said exists (data changed mid-pull,
    # pages shifted, ...). Keep the file, but flag it so we notice.
    logger.warning(
        "Count mismatch: api_total=%s but records_received=%s",
        api_total,
        records_received,
    )
    return "count_mismatch"


def main(max_pages: int | None = None) -> dict:
    """Run one daily collection: records.jsonl + _manifest.json. Return the manifest.

    On any failure a manifest with status="failed" is still written, then the error
    is re-raised so the process exits non-zero and the scheduler marks the run as failed.
    """
    ingest_date = today_ist()  # business date -> IST
    out_dir = get_output_dir(ingest_date)

    manifest = {
        "ingest_date": ingest_date,
        "source": "data.gov.in",
        "resource_id": CURRENT_PRICES_RESOURCE_ID,
        "started_at": utc_now(),  # timestamps -> UTC
        "max_pages": max_pages,
    }

    try:
        counts = write_records(out_dir, max_pages=max_pages)
    except Exception as error:
        manifest["status"] = "failed"
        manifest["finished_at"] = utc_now()
        # Our own AgmarknetAPIError messages are safe to store. For anything else store only
        # the error type: other exceptions' messages can contain the URL, and with it the API key.
        if isinstance(error, AgmarknetAPIError):
            manifest["error"] = str(error)
        else:
            manifest["error"] = type(error).__name__
        write_manifest(out_dir, manifest)
        raise

    manifest.update(counts)
    manifest["status"] = decide_status(
        counts["api_total"], counts["records_received"], max_pages
    )
    manifest["finished_at"] = utc_now()
    write_manifest(out_dir, manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect today's mandi prices.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Testing shortcut: stop after N pages (default: download everything).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    main(max_pages=args.max_pages)
