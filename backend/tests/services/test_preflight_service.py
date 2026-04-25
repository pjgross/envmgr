"""Unit tests for preflight_service.evaluate — the can-deploy gate."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.build import Build
from app.db.models.change_request import (
    ChangeRequest,
    ChangeRequestEnvironment,
)
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import System, SubSystem
from app.services import preflight_service


async def _scaffold(db_session, tenant, user):
    """Create a system, subsystem, environment + booking type/lifecycle for tests."""
    sys_row = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys_row)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys_row.id, name="orders-api")
    env = Environment(
        tenant_id=tenant.id,
        name="sit",
        environment_type="integration",
        status=EnvironmentStatus.ACTIVE,
    )
    db_session.add_all([sub, env])
    await db_session.flush()

    # Booking type + lifecycle for booking creation
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="booking",
        name="default",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(tenant_id=tenant.id, name="Standard", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.flush()

    # CR lifecycle template (for change-request rule tests)
    cr_tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="change_request",
        name="cr-default",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(cr_tpl)
    await db_session.commit()

    return {
        "system": sys_row,
        "subsystem": sub,
        "environment": env,
        "booking_type": bt,
        "cr_lifecycle": cr_tpl,
    }


async def _make_booking(
    db_session,
    *,
    tenant,
    user,
    booking_type,
    environment,
    start: datetime,
    end: datetime,
    exclusive: bool,
    status: str = "approved",
    release_id: int | None = None,
):
    req = BookingRequest(
        tenant_id=tenant.id,
        project_name="Q2 regression — checkout team",
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        exclusive_use_requested=exclusive,
        booked_by=user.id,
    )
    db_session.add(req)
    await db_session.flush()
    booking = Booking(
        tenant_id=tenant.id,
        environment_id=environment.id,
        start_date=start,
        end_date=end,
        status=status,
        release_id=release_id,
        booking_request_id=req.id,
    )
    db_session.add(booking)
    await db_session.commit()
    await db_session.refresh(booking)
    return booking


async def _make_cr(
    db_session,
    *,
    tenant,
    user,
    lifecycle,
    environment,
    has_outage: bool = True,
    outage_start: datetime,
    outage_end: datetime,
    subsystem_id: int | None = None,
):
    cr = ChangeRequest(
        tenant_id=tenant.id,
        title="DB upgrade",
        change_type="infrastructure",
        status="approved",
        lifecycle_id=lifecycle.id,
        subsystem_id=subsystem_id,
        has_outage=has_outage,
        outage_start=outage_start,
        outage_end=outage_end,
        scheduled_start=outage_start,
        scheduled_end=outage_end,
        raised_by=user.id,
    )
    db_session.add(cr)
    await db_session.flush()
    db_session.add(ChangeRequestEnvironment(
        change_request_id=cr.id,
        environment_id=environment.id,
        tenant_id=tenant.id,
    ))
    await db_session.commit()
    await db_session.refresh(cr)
    return cr


@pytest.mark.asyncio
async def test_all_clear_returns_ok_true(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    assert resp.ok is True
    assert resp.blockers == []
    assert resp.warnings == []
    assert resp.claim_matched is None
    assert resp.environment_slug == "sit"
    assert resp.subsystem_slug == "orders-api"


@pytest.mark.asyncio
async def test_environment_inactive_blocks(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    s["environment"].status = EnvironmentStatus.MAINTENANCE
    await db_session.commit()

    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    assert resp.ok is False
    assert len(resp.blockers) == 1
    b = resp.blockers[0]
    assert b.type == "environment_inactive"
    assert b.ref_kind == "environment"
    assert b.ref_id == s["environment"].id
    assert b.current_status == "maintenance"


@pytest.mark.asyncio
async def test_environment_not_found_404(db_session, tenant, user):
    await _scaffold(db_session, tenant, user)
    with pytest.raises(HTTPException) as exc_info:
        await preflight_service.evaluate(
            db_session,
            tenant_id=tenant.id,
            environment_slug="nonexistent",
            subsystem_slug="orders-api",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_subsystem_not_found_404(db_session, tenant, user):
    await _scaffold(db_session, tenant, user)
    with pytest.raises(HTTPException) as exc_info:
        await preflight_service.evaluate(
            db_session,
            tenant_id=tenant.id,
            environment_slug="sit",
            subsystem_slug="missing-sub",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_exclusive_booking_blocks_without_claim(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    booking = await _make_booking(
        db_session,
        tenant=tenant, user=user,
        booking_type=s["booking_type"], environment=s["environment"],
        start=now - timedelta(hours=1), end=now + timedelta(hours=2),
        exclusive=True,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    assert resp.ok is False
    assert resp.claim_matched is None
    assert len(resp.blockers) == 1
    b = resp.blockers[0]
    assert b.type == "exclusive_booking"
    assert b.ref_kind == "booking"
    assert b.ref_id == booking.id
    assert b.title == "Q2 regression — checkout team"


@pytest.mark.asyncio
async def test_exclusive_booking_unlocked_by_booking_id_claim(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    booking = await _make_booking(
        db_session,
        tenant=tenant, user=user,
        booking_type=s["booking_type"], environment=s["environment"],
        start=now - timedelta(hours=1), end=now + timedelta(hours=2),
        exclusive=True,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
        booking_id=booking.id,
    )
    assert resp.ok is True
    assert resp.blockers == []
    assert resp.claim_matched is not None
    assert resp.claim_matched.booking_id == booking.id
    assert resp.claim_matched.matched_via == "booking_id"
    assert resp.claim_matched.claim_value == booking.id


@pytest.mark.asyncio
async def test_exclusive_booking_unlocked_by_release_id_claim(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    booking = await _make_booking(
        db_session,
        tenant=tenant, user=user,
        booking_type=s["booking_type"], environment=s["environment"],
        start=now - timedelta(hours=1), end=now + timedelta(hours=2),
        exclusive=True,
        release_id=42,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
        release_id=42,
    )
    assert resp.ok is True
    assert resp.blockers == []
    assert resp.claim_matched is not None
    assert resp.claim_matched.booking_id == booking.id
    assert resp.claim_matched.matched_via == "release_id"
    assert resp.claim_matched.claim_value == 42


@pytest.mark.asyncio
async def test_exclusive_booking_release_id_mismatch_blocks(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    await _make_booking(
        db_session,
        tenant=tenant, user=user,
        booking_type=s["booking_type"], environment=s["environment"],
        start=now - timedelta(hours=1), end=now + timedelta(hours=2),
        exclusive=True,
        release_id=42,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
        release_id=43,
    )
    assert resp.ok is False
    assert resp.claim_matched is None
    assert len(resp.blockers) == 1
    assert resp.blockers[0].type == "exclusive_booking"


@pytest.mark.asyncio
async def test_change_request_outage_blocks(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    cr = await _make_cr(
        db_session,
        tenant=tenant, user=user,
        lifecycle=s["cr_lifecycle"],
        environment=s["environment"],
        has_outage=True,
        outage_start=now - timedelta(hours=1),
        outage_end=now + timedelta(hours=1),
        subsystem_id=None,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    assert resp.ok is False
    assert any(
        b.type == "change_request_outage" and b.ref_id == cr.id and b.ref_kind == "change_request"
        for b in resp.blockers
    )


@pytest.mark.asyncio
async def test_change_request_outage_different_subsystem_does_not_block(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    other_sub = SubSystem(
        tenant_id=tenant.id, system_id=s["system"].id, name="other-api",
    )
    db_session.add(other_sub)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    await _make_cr(
        db_session,
        tenant=tenant, user=user,
        lifecycle=s["cr_lifecycle"],
        environment=s["environment"],
        has_outage=True,
        outage_start=now - timedelta(hours=1),
        outage_end=now + timedelta(hours=1),
        subsystem_id=other_sub.id,  # narrowed to a different subsystem
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    # No CR blocker because the CR is scoped to a different subsystem
    assert not any(b.type == "change_request_outage" for b in resp.blockers)


@pytest.mark.asyncio
async def test_non_exclusive_booking_warns_does_not_block(db_session, tenant, user):
    s = await _scaffold(db_session, tenant, user)
    now = datetime.now(timezone.utc)
    booking = await _make_booking(
        db_session,
        tenant=tenant, user=user,
        booking_type=s["booking_type"], environment=s["environment"],
        start=now - timedelta(hours=1), end=now + timedelta(hours=2),
        exclusive=False,
    )
    resp = await preflight_service.evaluate(
        db_session,
        tenant_id=tenant.id,
        environment_slug="sit",
        subsystem_slug="orders-api",
    )
    assert resp.ok is True
    assert resp.blockers == []
    assert len(resp.warnings) == 1
    w = resp.warnings[0]
    assert w.type == "non_exclusive_booking"
    assert w.ref_kind == "booking"
    assert w.ref_id == booking.id
    assert w.until is not None
