"""Upload one day's raw collection (records.jsonl + _manifest.json) to a Databricks Volume.

Local:   data/raw/agmarknet/ingest_date=YYYY-MM-DD/{records.jsonl, _manifest.json}
Remote:  <DATABRICKS_VOLUME_ROOT>/agmarknet/ingest_date=YYYY-MM-DD/{records.jsonl, _manifest.json}

Auth comes from DATABRICKS_HOST and DATABRICKS_TOKEN (read automatically by the SDK).
Uses the Databricks Files API, so no Databricks compute is needed.

Run (from the project root):  python -m ingestion.upload_to_volume [--date YYYY-MM-DD]

Author: Vijay (github.com/Vijayrajdev)
"""

import argparse
import json
import logging
import os
from pathlib import Path

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv

from ingestion.collect_daily import get_output_dir, today_ist

load_dotenv()
logger = logging.getLogger(__name__)

# Unity Catalog volume path: /Volumes/<catalog>/<schema>/<volume>
DEFAULT_VOLUME_ROOT = "/Volumes/mandi-pulse/mandi/raw"

# Upload order matters: records first, manifest LAST.
# The manifest is the "commit marker" - anything reading the volume should only trust
# a folder once its _manifest.json says success. If the upload dies after records.jsonl,
# there's no new manifest yet, so nobody mistakes a half-uploaded day for a finished one.
FILES_IN_ORDER = ("records.jsonl", "_manifest.json")


def get_volume_root() -> str:
    """Read the volume root from DATABRICKS_VOLUME_ROOT (no trailing slash)."""
    return os.getenv("DATABRICKS_VOLUME_ROOT", DEFAULT_VOLUME_ROOT).rstrip("/")


def read_manifest(local_dir: Path) -> dict:
    """Load the local _manifest.json, failing clearly if it's missing."""
    manifest_path = local_dir / "_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest at {manifest_path} - run the collector first"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def upload_run(
    local_dir: Path,
    ingest_date: str,
    client: WorkspaceClient | None = None,
) -> str:
    """Upload records.jsonl then _manifest.json to the Volume. Return the remote folder.

    ``client`` can be passed in (e.g. a fake in tests); otherwise one is created from env vars.
    """
    manifest = read_manifest(local_dir)

    # Never publish a failed run: its records.jsonl may be missing or from an older run.
    if manifest.get("status") == "failed":
        raise ValueError(
            f"Manifest for {ingest_date} has status=failed - not uploading"
        )
    # Test runs (--max-pages) shouldn't overwrite a real day's data in the volume.
    if manifest.get("status") == "partial":
        raise ValueError(
            f"Manifest for {ingest_date} is a partial test run - not uploading"
        )

    w = client or WorkspaceClient()
    remote_dir = f"{get_volume_root()}/agmarknet/ingest_date={ingest_date}"

    # Like mkdir(parents=True, exist_ok=True): creates missing folders, no error if they exist.
    w.files.create_directory(remote_dir)

    for name in FILES_IN_ORDER:
        local_path = local_dir / name
        if not local_path.exists():
            raise FileNotFoundError(f"Missing {local_path}")

        remote_path = f"{remote_dir}/{name}"
        size_kb = local_path.stat().st_size / 1024
        logger.info("Uploading %s (%.0f KB) -> %s", local_path, size_kb, remote_path)

        # 'rb' = read bytes: the SDK sends the raw file content.
        # overwrite=True makes re-running the same day safe (idempotent).
        with open(local_path, "rb") as f:
            w.files.upload(remote_path, f, overwrite=True)

    logger.info(
        "Uploaded %s (status=%s, records=%s)",
        remote_dir,
        manifest.get("status"),
        manifest.get("records_received"),
    )
    return remote_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Upload a day's raw files to Databricks."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Ingest date YYYY-MM-DD (default: today in IST).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    date = args.date or today_ist()
    upload_run(get_output_dir(date), date)
