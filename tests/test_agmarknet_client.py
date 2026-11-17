"""Tests for ingestion/agmarknet_client.py: requests, retries and pagination."""

from unittest import mock

import pytest
import requests

from ingestion import agmarknet_client as client
from tests.conftest import FAKE_KEY, make_page, make_response

OK_BODY = {"total": 1, "records": [{"market": "Mukkom Market"}]}


def fake_get(*responses):
    """Patch requests.get to return/raise the given items, one per call, in order."""
    return mock.patch.object(client.requests, "get", side_effect=list(responses))


# --- fetch_page --------------------------------------------------------------------------


def test_fetch_page_sends_params_header_and_timeout():
    with fake_get(make_response(200, OK_BODY)) as get:
        assert client.fetch_page(offset=1000, limit=500) == OK_BODY

    kwargs = get.call_args.kwargs
    assert kwargs["params"]["offset"] == 1000
    assert kwargs["params"]["limit"] == 500
    assert kwargs["params"]["format"] == "json"
    assert kwargs["params"]["api-key"] == FAKE_KEY
    # The server stalls the default python-requests User-Agent (see docs/source_notes.md).
    assert "mandi-pulse" in kwargs["headers"]["User-Agent"]
    # Without a timeout a hung API would block forever.
    assert kwargs["timeout"] == client.TIMEOUT


def test_fetch_page_uses_requested_resource_id():
    with fake_get(make_response(200, OK_BODY)) as get:
        client.fetch_page(0, 5, resource_id=client.HISTORICAL_PRICES_RESOURCE_ID)

    called_url = get.call_args.args[0]
    assert called_url.endswith(client.HISTORICAL_PRICES_RESOURCE_ID)


@pytest.mark.parametrize("value", [None, ""])
def test_fetch_page_fails_clearly_without_api_key(monkeypatch, value):
    # parametrize runs this test twice: key missing entirely, and key set but empty.
    if value is None:
        monkeypatch.delenv("DATA_GOV_API_KEY")
    else:
        monkeypatch.setenv("DATA_GOV_API_KEY", value)

    with pytest.raises(RuntimeError, match="DATA_GOV_API_KEY"):
        client.fetch_page(0, 5)


# --- fetch_page_with_retry -----------------------------------------------------------------


def test_retries_on_503_then_succeeds(no_sleep):
    with fake_get(make_response(503), make_response(200, OK_BODY)) as get:
        assert client.fetch_page_with_retry(0, 5) == OK_BODY

    assert get.call_count == 2
    assert no_sleep == [2]  # waited once, 2 seconds


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_all_retryable_statuses_are_retried(status):
    with fake_get(make_response(status), make_response(200, OK_BODY)) as get:
        client.fetch_page_with_retry(0, 5)
    assert get.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_no_retry_on_client_errors(status, no_sleep):
    with (
        fake_get(make_response(status)) as get,
        pytest.raises(client.AgmarknetAPIError, match=f"HTTP {status}"),
    ):
        client.fetch_page_with_retry(0, 5)

    assert get.call_count == 1  # failed fast, no second attempt
    assert no_sleep == []


def test_gives_up_after_max_attempts_with_exponential_backoff(no_sleep):
    timeouts = [requests.exceptions.ReadTimeout("slow")] * 5
    with (
        fake_get(*timeouts) as get,
        pytest.raises(client.AgmarknetAPIError, match="after 5 attempts"),
    ):
        client.fetch_page_with_retry(0, 5, max_attempts=5)

    assert get.call_count == 5
    assert no_sleep == [
        2,
        4,
        8,
        16,
    ]  # doubles each time, no sleep after the last attempt


def test_retries_connection_errors():
    with fake_get(
        requests.exceptions.ConnectionError("reset"), make_response(200, OK_BODY)
    ) as get:
        assert client.fetch_page_with_retry(0, 5) == OK_BODY
    assert get.call_count == 2


def test_retries_chunked_encoding_error():
    # Regression (2026-11-12/13/15): the connection broke mid-body and the run died
    # on the first attempt because this error type wasn't retried.
    with fake_get(
        requests.exceptions.ChunkedEncodingError("Connection broken"),
        make_response(200, OK_BODY),
    ) as get:
        assert client.fetch_page_with_retry(0, 5) == OK_BODY
    assert get.call_count == 2


def test_retries_truncated_json():
    # A 200 response whose body was cut off - happens with very large pages.
    truncated = make_response(200, raw=b'{"records": [{"market": "Muk')
    with fake_get(truncated, make_response(200, OK_BODY)) as get:
        assert client.fetch_page_with_retry(0, 5) == OK_BODY
    assert get.call_count == 2


def test_errors_never_contain_the_api_key():
    with (
        fake_get(make_response(403)),
        pytest.raises(client.AgmarknetAPIError) as caught,
    ):
        client.fetch_page_with_retry(0, 5)

    error = caught.value
    assert FAKE_KEY not in str(error)
    # 'from None' must drop the original requests error (whose message has the URL + key).
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


# --- iter_pages --------------------------------------------------------------------------


def test_iter_pages_stops_when_offset_reaches_total():
    pages = [make_page([1, 2], total=3), make_page([3], total=3)]
    with mock.patch.object(client, "fetch_page_with_retry", side_effect=pages) as fetch:
        result = list(client.iter_pages(page_size=2))

    assert len(result) == 2
    assert [c.kwargs["offset"] for c in fetch.call_args_list] == [0, 2]


def test_iter_pages_retries_suspicious_empty_page_then_continues(no_sleep):
    # Regression (2026-11-17): page 3 came back empty with total=0 while 17,441 rows
    # existed, and we silently stopped at 2,000. Now the empty page is re-asked.
    pages = [
        make_page([1, 2], total=4),
        make_page([], total=0),  # glitch
        make_page([3, 4], total=4),  # same offset, asked again -> real data
    ]
    with mock.patch.object(client, "fetch_page_with_retry", side_effect=pages) as fetch:
        result = list(client.iter_pages(page_size=2))

    assert [r for page in result for r in page["records"]] == [1, 2, 3, 4]
    assert [c.kwargs["offset"] for c in fetch.call_args_list] == [0, 2, 2]
    assert no_sleep == [2]


def test_iter_pages_fails_if_empty_page_persists_before_total(no_sleep):
    # Better to fail loudly than to save a fraction of the day as if it were complete.
    pages = [make_page([1, 2], total=99)] + [
        make_page([], total=0)
    ] * client.EMPTY_PAGE_RETRIES
    with (
        mock.patch.object(client, "fetch_page_with_retry", side_effect=pages),
        pytest.raises(client.AgmarknetAPIError, match="Empty page at offset=2"),
    ):
        list(client.iter_pages(page_size=2))

    assert len(no_sleep) == client.EMPTY_PAGE_RETRIES - 1


def test_iter_pages_trusts_first_total_not_later_ones():
    # A later page reporting a smaller total must not end the run early.
    pages = [
        make_page([1, 2], total=6),
        make_page([3, 4], total=2),  # glitchy total on a non-empty page
        make_page([5, 6], total=6),
    ]
    with mock.patch.object(client, "fetch_page_with_retry", side_effect=pages):
        result = list(client.iter_pages(page_size=2))

    assert len(result) == 3


def test_iter_pages_empty_page_at_true_end_is_fine(no_sleep):
    # total=4 but the API only has 3 rows: page at offset 2 has 1 row, then we stop
    # because offset 4 >= total - no extra request, no retries.
    pages = [make_page([1, 2], total=4), make_page([3], total=4)]
    with mock.patch.object(client, "fetch_page_with_retry", side_effect=pages):
        result = list(client.iter_pages(page_size=2))

    assert len(result) == 2
    assert no_sleep == []


def test_iter_pages_yields_nothing_when_api_is_empty():
    with mock.patch.object(
        client, "fetch_page_with_retry", side_effect=[make_page([], total=0)]
    ):
        assert list(client.iter_pages()) == []
