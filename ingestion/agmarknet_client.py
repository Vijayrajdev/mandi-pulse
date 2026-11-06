"""Client for the data.gov.in Mandi price APIs (current daily prices + historical prices).

Provides three layers, each building on the one before:

1. ``fetch_page``             - one HTTP request for one page of records.
2. ``fetch_page_with_retry``  - same, but retries temporary failures with exponential backoff.
3. ``iter_pages``             - generator that walks through every page until the data runs out.

Source quirks this code handles are documented in ``docs/source_notes.md``.

Author: Vijay (github.com/Vijayrajdev)
"""

import logging
import os
import time
from collections.abc import Iterator

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

API_ROOT = "https://api.data.gov.in/resource"

# "Current Daily Price of Various Commodities from Various Markets (Mandi)"
# Only today's prices (~6-13k rows). Used by the daily collector. Default.
CURRENT_PRICES_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"

# "Variety-wise Daily Market Prices Data of Commodity"
# Full history since 2010 (~83M rows). Candidate source for backfill. Field names are Capitalised.
HISTORICAL_PRICES_RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"

# (connect, read) seconds. Connecting should be quick; reading 1000 rows from this API can be slow.
TIMEOUT = (10, 60)

# Server stalls the default "python-requests" User-Agent - see docs/source_notes.md
HEADERS = {
    "User-Agent": "mandi-pulse/0.1 (+https://github.com/Vijayrajdev/mandi-pulse)"
}

# Very large pages (e.g. limit=10000) come back as truncated JSON - see docs/source_notes.md.
DEFAULT_PAGE_SIZE = 1000

# Server-side / rate-limit errors that usually go away if we wait and try again.
# Anything else (400 bad request, 403 bad key, 404 ...) is our problem, so we fail fast.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AgmarknetAPIError(Exception):
    """Raised when the API cannot be read. The message never contains the API key."""


def _get_api_key() -> str:
    """Read the API key at call time (not import time) so tests can import this module without a key."""
    api_key = os.getenv("DATA_GOV_API_KEY")
    if not api_key:  # catches both a missing variable (None) and an empty value ("")
        raise RuntimeError("DATA_GOV_API_KEY is not set - add it to .env")
    return api_key


def fetch_page(
    offset: int,
    limit: int = DEFAULT_PAGE_SIZE,
    resource_id: str = CURRENT_PRICES_RESOURCE_ID,
) -> dict:
    """Fetch one page of records. Raises requests exceptions on any failure."""
    logger.info(
        "Fetching resource=%s offset=%s limit=%s", resource_id[:8], offset, limit
    )

    query_params = {
        "api-key": _get_api_key(),
        "format": "json",
        "limit": limit,
        "offset": offset,
    }

    url = f"{API_ROOT}/{resource_id}"
    response = requests.get(url, params=query_params, headers=HEADERS, timeout=TIMEOUT)
    # Turns any 4xx/5xx status into an HTTPError, so callers handle failures with try/except.
    response.raise_for_status()
    # A 200 response can still be cut off mid-body; .json() then raises JSONDecodeError.
    return response.json()


def fetch_page_with_retry(
    offset: int,
    limit: int = DEFAULT_PAGE_SIZE,
    max_attempts: int = 5,
    resource_id: str = CURRENT_PRICES_RESOURCE_ID,
) -> dict:
    """Fetch one page, retrying temporary failures with exponential backoff (2s, 4s, 8s, ...)."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_page(offset=offset, limit=limit, resource_id=resource_id)

        except requests.exceptions.HTTPError as error:
            status = error.response.status_code
            if status not in RETRYABLE_STATUS:
                # Retrying won't fix a bad key or a bad request - stop immediately.
                logger.error(
                    "Offset=%s failed with HTTP %s (not retryable)", offset, status
                )
                # 'from None' drops the original exception, whose message includes the URL + API key.
                raise AgmarknetAPIError(f"HTTP {status} at offset={offset}") from None
            reason = f"HTTP {status}"

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as error:
            reason = type(error).__name__  # e.g. "ReadTimeout"

        except requests.exceptions.JSONDecodeError:
            reason = "truncated/invalid JSON"

        if attempt == max_attempts:
            logger.error(
                "Offset=%s failed after %s attempts (last error: %s)",
                offset,
                max_attempts,
                reason,
            )
            raise AgmarknetAPIError(
                f"Gave up at offset={offset} after {max_attempts} attempts: {reason}"
            ) from None

        wait_seconds = 2**attempt  # 2, 4, 8, 16, ...
        logger.warning(
            "Attempt %s/%s at offset=%s failed (%s), retrying in %ss",
            attempt,
            max_attempts,
            offset,
            reason,
            wait_seconds,
        )
        time.sleep(wait_seconds)

    # Only reachable if max_attempts < 1.
    raise ValueError("max_attempts must be at least 1")


def iter_pages(
    page_size: int = DEFAULT_PAGE_SIZE,
    resource_id: str = CURRENT_PRICES_RESOURCE_ID,
) -> Iterator[dict]:
    """Yield every page of a dataset, one page (the full API response) at a time.

    Don't call this on the historical dataset without filters - that's ~83k requests.

    Each yielded page includes metadata such as ``total`` and ``updated_date``,
    which the daily collector needs for its manifest.

    Stops when a page comes back empty or we have paged past ``total``.
    """
    offset = 0
    while True:
        page = fetch_page_with_retry(
            offset=offset, limit=page_size, resource_id=resource_id
        )
        records = page.get("records", [])
        total = int(page.get("total", 0))  # 'total' is an int, but convert defensively

        logger.info(
            "Got %s records at offset=%s (api total=%s)", len(records), offset, total
        )

        if not records:
            break

        yield page

        offset += page_size
        if offset >= total:
            break


if __name__ == "__main__":
    # Manual smoke test: fetch the first small page and print a summary (never the raw response).
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    first_page = fetch_page_with_retry(offset=0, limit=5)
    logger.info(
        "OK: total=%s, received=%s, updated_date=%s",
        first_page.get("total"),
        len(first_page.get("records", [])),
        first_page.get("updated_date"),
    )
