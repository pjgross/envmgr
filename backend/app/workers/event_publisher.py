"""Background worker: polls EventLog for unpublished events and publishes to NATS JetStream."""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.db.models.event_log import EventLog

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5  # seconds
_BATCH_SIZE = 50
_RETRY_BACKOFF = [5, 10, 30, 60]  # backoff seconds on repeated NATS failures


async def _connect_nats():
    """Attempt to connect to NATS, returning (nc, js) or raising."""
    import nats

    nc = await nats.connect(settings.NATS_URL)
    js = nc.jetstream()
    try:
        await js.add_stream(name="ENVMGR_EVENTS", subjects=["envmgr.events.>"])
    except Exception as e:
        logger.warning("NATS stream creation warning: %s", e)
    return nc, js


async def _publish_batch(js, events: list[EventLog]) -> None:
    """Publish a list of EventLog rows to NATS JetStream."""
    for event in events:
        subject = f"envmgr.events.{event.aggregate_type}.{event.event_type}"
        data = json.dumps(
            {
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "aggregate_type": event.aggregate_type,
                "payload": event.payload,
                "tenant_id": event.tenant_id,
                "created_at": event.created_at.isoformat(),
            }
        ).encode()
        await js.publish(subject, data)
        event.published_at = datetime.now(timezone.utc)


async def run_event_publisher() -> None:
    """
    Long-running background task.

    Connects to NATS with retry/backoff so that a missing NATS instance
    (e.g. in test environments) does not crash the application on startup.
    Once connected, polls every _POLL_INTERVAL seconds for unpublished events.
    On NATS failure during polling, reconnects with backoff.
    """
    attempt = 0
    nc = None
    js = None

    while True:
        # (Re-)connect phase
        if js is None:
            backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            try:
                nc, js = await _connect_nats()
                logger.info("Event publisher connected to NATS at %s", settings.NATS_URL)
                attempt = 0
            except Exception as exc:
                logger.warning(
                    "Event publisher: NATS connection failed (attempt %d): %s. "
                    "Retrying in %d s.",
                    attempt + 1,
                    exc,
                    backoff,
                )
                attempt += 1
                await asyncio.sleep(backoff)
                continue

        # Poll phase
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(EventLog)
                    .where(EventLog.published_at.is_(None))
                    .order_by(EventLog.created_at)
                    .limit(_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
                events = list(result.scalars().all())

                if events:
                    try:
                        await _publish_batch(js, events)
                    except Exception as nats_exc:
                        logger.error(
                            "Event publisher: NATS publish failed: %s. Will reconnect.",
                            nats_exc,
                        )
                        if nc is not None:
                            try:
                                await nc.close()
                            except Exception:
                                pass
                        nc = None
                        js = None
                        attempt += 1
                        await asyncio.sleep(
                            _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        )
                        continue
                    await db.commit()
                    logger.info("Published %d event(s) to NATS.", len(events))

        except Exception as exc:
            logger.error("Event publisher: database error: %s.", exc)
            await asyncio.sleep(_POLL_INTERVAL)
            continue

        await asyncio.sleep(_POLL_INTERVAL)


_SUPERVISOR_BACKOFF = [1, 5, 15, 30, 60]  # seconds between restarts


async def supervise_event_publisher() -> None:
    """Keep run_event_publisher running for the life of the process.

    run_event_publisher handles NATS and database failures itself, but it was
    launched with a bare asyncio.create_task: anything it *didn't* catch killed
    the task silently, and the outbox then stopped draining forever with no
    signal beyond events quietly never arriving. A dead publisher is invisible
    precisely because its job is to happen in the background.

    Restarts with backoff and logs each restart at ERROR so it shows up in
    alerting. Cancellation (shutdown) is propagated, not restarted.
    """
    failures = 0
    while True:
        try:
            await run_event_publisher()
            # A clean return is not expected — the worker loops forever.
            logger.error("Event publisher returned unexpectedly; restarting.")
        except asyncio.CancelledError:
            logger.info("Event publisher cancelled; shutting down.")
            raise
        except Exception:
            logger.exception("Event publisher crashed; restarting.")

        backoff = _SUPERVISOR_BACKOFF[min(failures, len(_SUPERVISOR_BACKOFF) - 1)]
        failures += 1
        await asyncio.sleep(backoff)
