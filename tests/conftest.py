"""Shared test fixtures.

Fixtures are reusable setup functions. Those marked autouse=True apply to EVERY test
automatically, which is how we guarantee no test ever hits the real API or sleeps.
"""

import json

import pytest
import requests

from ingestion import agmarknet_client

FAKE_KEY = "TEST-KEY-not-a-real-key-123"


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    """Every test gets a fake API key and its own empty DATA_DIR.

    monkeypatch undoes all changes after each test, so tests can't leak into each other
    (or into your real .env values / data/ folder).
    """
    monkeypatch.setenv("DATA_GOV_API_KEY", FAKE_KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Safety net: any test that forgets to fake requests.get fails loudly instead of
    calling data.gov.in for real."""

    def _blocked(*args, **kwargs):
        raise RuntimeError("Real network call attempted in a test - fake requests.get")

    monkeypatch.setattr(agmarknet_client.requests, "get", _blocked)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries back off 2s, 4s, 8s... - skip the waiting in tests. Returns the list of
    requested sleep durations so tests can check the backoff."""
    sleeps = []
    monkeypatch.setattr(agmarknet_client.time, "sleep", sleeps.append)
    return sleeps


def make_response(
    status: int, body=None, raw: bytes | None = None
) -> requests.Response:
    """Build a real requests.Response without any network.

    body -> JSON-encoded; raw -> exact bytes (use for truncated/invalid JSON).
    The URL contains the fake key so tests can prove it never leaks into errors.
    """
    response = requests.Response()
    response.status_code = status
    response.url = f"https://api.data.gov.in/resource/x?api-key={FAKE_KEY}"
    response._content = raw if raw is not None else json.dumps(body or {}).encode()
    return response


def make_page(
    records: list, total: int, updated_date: str = "2026-11-10T07:00:00Z"
) -> dict:
    """A fake API page in the same shape data.gov.in returns."""
    return {
        "total": total,
        "count": len(records),
        "limit": str(len(records)),
        "offset": "0",
        "updated_date": updated_date,
        "records": records,
    }
