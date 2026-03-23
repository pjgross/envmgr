"""Unit tests for event_publisher worker.

Mocks NATS connection to verify that unpublished EventLog rows get picked up
and that published_at is set after publishing.
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_event(event_id: int, event_type: str = "EnvironmentCreated"):
    """Build a fake event object mimicking EventLog (not a real ORM instance)."""
    evt = MagicMock()
    evt.id = event_id
    evt.event_type = event_type
    evt.aggregate_id = event_id * 10
    evt.aggregate_type = "Environment"
    evt.payload = {"id": event_id * 10, "name": f"Env{event_id}", "tenant_id": 1}
    evt.tenant_id = 1
    evt.published_at = None
    evt.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return evt


@pytest.mark.asyncio
async def test_publisher_sets_published_at_on_success():
    """Unpublished events are published and published_at is set."""
    from app.workers.event_publisher import _publish_batch

    events = [_make_event(1), _make_event(2)]
    mock_js = AsyncMock()

    await _publish_batch(mock_js, events)

    # Both events should have published_at set
    for evt in events:
        assert evt.published_at is not None
        assert isinstance(evt.published_at, datetime)

    # js.publish should have been called once per event
    assert mock_js.publish.call_count == 2


@pytest.mark.asyncio
async def test_publisher_uses_correct_nats_subject():
    """NATS subject is formatted as envmgr.events.<aggregate_type>.<event_type>."""
    from app.workers.event_publisher import _publish_batch

    evt = _make_event(1, event_type="EnvironmentCreated")
    evt.aggregate_type = "Environment"
    mock_js = AsyncMock()

    await _publish_batch(mock_js, [evt])

    subject_used = mock_js.publish.call_args[0][0]
    assert subject_used == "envmgr.events.Environment.EnvironmentCreated"


@pytest.mark.asyncio
async def test_publisher_payload_contains_required_fields():
    """Published JSON payload contains event_type, aggregate_id, aggregate_type, tenant_id, created_at."""
    from app.workers.event_publisher import _publish_batch

    evt = _make_event(5)
    mock_js = AsyncMock()

    await _publish_batch(mock_js, [evt])

    raw_bytes = mock_js.publish.call_args[0][1]
    data = json.loads(raw_bytes.decode())
    assert data["event_type"] == evt.event_type
    assert data["aggregate_id"] == evt.aggregate_id
    assert data["aggregate_type"] == evt.aggregate_type
    assert data["tenant_id"] == evt.tenant_id
    assert "created_at" in data
    assert "payload" in data


@pytest.mark.asyncio
async def test_publisher_handles_nats_connect_failure_with_retry():
    """run_event_publisher retries when NATS is unavailable instead of crashing."""
    call_count = 0

    async def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionRefusedError("NATS not available")
        raise asyncio.CancelledError()

    with patch("app.workers.event_publisher._connect_nats", side_effect=side_effect), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            from app.workers.event_publisher import run_event_publisher
            await run_event_publisher()

    # Should have attempted at least once (before CancelledError on second try)
    assert call_count >= 1


@pytest.mark.asyncio
async def test_publisher_no_events_skips_commit():
    """When there are no unpublished events, db.commit is not called."""
    db_mock = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    db_mock.execute = AsyncMock(return_value=execute_result)
    db_mock.commit = AsyncMock()
    db_mock.__aenter__ = AsyncMock(return_value=db_mock)
    db_mock.__aexit__ = AsyncMock(return_value=False)

    mock_nc = AsyncMock()
    mock_js = AsyncMock()

    sleep_call_count = 0

    async def mock_sleep(n):
        nonlocal sleep_call_count
        sleep_call_count += 1
        if sleep_call_count >= 2:
            raise asyncio.CancelledError()

    async def mock_connect_nats():
        return mock_nc, mock_js

    with patch("app.workers.event_publisher._connect_nats", side_effect=mock_connect_nats), \
         patch("app.workers.event_publisher.AsyncSessionLocal", return_value=db_mock), \
         patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            from app.workers.event_publisher import run_event_publisher
            await run_event_publisher()

    # commit should NOT have been called since there were no events
    db_mock.commit.assert_not_called()
