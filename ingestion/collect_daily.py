"""Daily collector: pulls today's mandi prices and saves them as raw JSONL.

Output: data/raw/agmarknet/ingest_date=YYYY-MM-DD/records.jsonl + _manifest.json

Author: Vijay (github.com/Vijayrajdev)
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from ingestion.agmarknet_client import iter_pages

load_dotenv()
logger = logging.getLogger(__name__)

# Mandis, prices and arrival_date are all in Indian time, so partition folders use IST dates.
# (Timestamps such as started_at/finished_at stay in UTC.)
IST = ZoneInfo("Asia/Kolkata")


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
                    # non-English characters readable instead of ह escapes.
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


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    out_dir = get_output_dir(today_ist())
    # Quick test: one page only. Remove max_pages to download everything.
    print(write_records(out_dir, max_pages=1))
