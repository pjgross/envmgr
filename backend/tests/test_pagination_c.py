"""The five growth-bearing endpoints docs/pagination.md left unbounded.

The three that need only a URL are appended to the tables in test_pagination.py;
the two below need a real entity id in the path, so they get their own tests
here — the same shape as `test_release_subresource_conformance`.

Each also gets a page-walk over deliberately tied sort keys. The conformance
assertions prove the window exists; only the walk proves the tiebreaker does,
and both of these endpoints ordered by a non-unique column before this change
(`Deployment.deployed_at`, `BookingConflictAck.acknowledged_at`). See
test_pagination_ordering.py for why the PostgreSQL leg is the one that matters.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from tests.factories import ensure_build, ensure_change_request


async def _make_deployments(db_session, tenant_id, environment_id, count, *, deployed_at):
    """`count` deployments that all share one `deployed_at` — every row ties."""
    from app.db.models.deployment import Deployment

    cr = await ensure_change_request(db_session, tenant_id)
    for _ in range(count):
        build = await ensure_build(db_session, tenant_id)
        db_session.add(Deployment(
            tenant_id=tenant_id,
            build_id=build.id,
            environment_id=environment_id,
            change_request_id=cr.id,
            event_id=str(uuid.uuid4()),
            status="succeeded",
            deployed_at=deployed_at,
        ))
    await db_session.commit()


# ── GET /environments/{id}/deployments ───────────────────────────────────────


@pytest.mark.asyncio
async def test_environment_deployments_conformance(
    client, auth_headers, test_environment
):
    url = f"/api/v1/environments/{test_environment.id}/deployments"
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert isinstance(body, list)

    assert TOTAL_COUNT_HEADER in response.headers
    assert int(response.headers[TOTAL_COUNT_HEADER]) >= 0

    over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
    assert over.status_code == 422


@pytest.mark.asyncio
async def test_environment_deployments_total_counts_past_the_window(
    client, auth_headers, db_session, test_tenant, test_environment
):
    """The header must describe the whole set, not the page that came back."""
    await _make_deployments(
        db_session, test_tenant.id, test_environment.id, 5,
        deployed_at=datetime.now(timezone.utc),
    )

    response = await client.get(
        f"/api/v1/environments/{test_environment.id}/deployments?limit=2",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()) == 2
    assert int(response.headers[TOTAL_COUNT_HEADER]) == 5


@pytest.mark.asyncio
async def test_walking_environment_deployment_pages_sees_each_row_once(
    client, auth_headers, db_session, test_tenant, test_environment
):
    """Machine-pushed deployments share a timestamp routinely, so ties are ordinary."""
    total_rows = 12
    await _make_deployments(
        db_session, test_tenant.id, test_environment.id, total_rows,
        deployed_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )

    seen: list[int] = []
    page_size = 5
    offset = 0
    # An endpoint that ignores `limit` returns the whole set on every request,
    # so `rows` is never empty and an unguarded `while True` never terminates —
    # which is exactly the state this test starts in. Bound the walk by the
    # number of pages the rows can occupy and let the assertions below report
    # the failure, rather than hanging the suite.
    for _ in range(total_rows // page_size + 2):
        response = await client.get(
            f"/api/v1/environments/{test_environment.id}/deployments"
            f"?limit={page_size}&offset={offset}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        rows = response.json()
        if not rows:
            break
        assert len(rows) <= page_size, "the window was ignored"
        seen.extend(r["id"] for r in rows)
        offset += page_size

    assert len(seen) == total_rows, f"expected {total_rows} rows, saw {len(seen)}"
    assert len(set(seen)) == total_rows, "a row was returned on more than one page"


# ── GET /bookings/{id}/received-feedback ─────────────────────────────────────


async def _make_received_feedback(
    db_session, tenant_id, target_booking, source_bookings, user_id, *, acknowledged_at
):
    """One ack per source booking, every one sharing `acknowledged_at`."""
    from app.db.models.booking_conflict_ack import BookingConflictAck

    for source in source_bookings:
        db_session.add(BookingConflictAck(
            tenant_id=tenant_id,
            booking_id=source.id,
            other_booking_id=target_booking.id,
            acknowledged_by=user_id,
            willing_to_share=True,
            notes="shared",
            acknowledged_at=acknowledged_at,
        ))
    await db_session.commit()


# ── GET /tenant/users/lite ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_lite_orders_case_insensitively(
    client, auth_headers, db_session, test_tenant
):
    """Bounding this endpoint is what makes its collation matter.

    Both engines here collate by byte value (see `_sort_key` in
    app/core/pagination.py), so a bare `ORDER BY username` puts every
    capitalised name before every lowercase one. Unbounded that was merely an
    odd-looking picker; windowed, it decides *which users are droppable* —
    every lowercase username would be truncated before any capitalised one.
    """
    from app.core.security import get_password_hash
    from app.db.models.user import User

    for name in ("Zebra", "apple", "Mango"):
        db_session.add(User(
            tenant_id=test_tenant.id,
            username=name,
            email=f"{name}@test.com",
            password_hash=get_password_hash("password123"),
            role="Viewer",
            is_active=True,
        ))
    await db_session.commit()

    response = await client.get("/api/v1/tenant/users/lite", headers=auth_headers)
    assert response.status_code == 200, response.text

    returned = [u["username"] for u in response.json()]
    ours = [n for n in returned if n in ("Zebra", "apple", "Mango")]
    assert ours == ["apple", "Mango", "Zebra"]


@pytest.mark.asyncio
async def test_received_feedback_conformance(client, auth_headers, test_booking):
    url = f"/api/v1/bookings/{test_booking.id}/received-feedback"
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert isinstance(body, list)

    assert TOTAL_COUNT_HEADER in response.headers
    assert int(response.headers[TOTAL_COUNT_HEADER]) >= 0

    over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
    assert over.status_code == 422


@pytest.mark.asyncio
async def test_received_feedback_total_counts_past_the_window(
    client, auth_headers, db_session, test_tenant, test_user,
    test_booking, test_conflicting_booking,
):
    await _make_received_feedback(
        db_session, test_tenant.id, test_booking, [test_conflicting_booking],
        test_user.id, acknowledged_at=datetime.now(timezone.utc),
    )

    response = await client.get(
        f"/api/v1/bookings/{test_booking.id}/received-feedback?limit=1",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert int(response.headers[TOTAL_COUNT_HEADER]) == 1
