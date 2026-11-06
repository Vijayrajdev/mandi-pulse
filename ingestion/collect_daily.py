"""Daily collector: pulls today's mandi prices and saves them as raw JSONL.

Output: data/raw/agmarknet/ingest_date=YYYY-MM-DD/records.jsonl + _manifest.json

Author: Vijay (github.com/Vijayrajdev)
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

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


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    get_output_dir(today_ist())
