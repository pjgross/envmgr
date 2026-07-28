import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import select as _sel
from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.change_request import ChangeRequest, ChangeRequestEnvironment
from app.db.models.lifecycle import LifecycleTemplate
from app.services import environment_health_service as svc

UTC = timezone.utc

async def _env(db, tenant_id, name="Env A", status="active"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="SIT", status=status)
    db.add(e); await db.flush(); return e


async def _ensure_booking_type(db, tenant_id) -> BookingType:
    """Return an existing BookingType for tenant, or create one."""
    existing = (await db.execute(_sel(BookingType).where(BookingType.tenant_id == tenant_id).limit(1))).scalars().first()
    if existing:
        return existing
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="booking", name="health-test-booking",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [], "field_permissions": {},
        },
    )
    db.add(tpl)
    await db.flush()
    bt = BookingType(tenant_id=tenant_id, name="health-test", lifecycle_template_id=tpl.id)
    db.add(bt)
    await db.flush()
    return bt


async def _ensure_cr_lifecycle(db, tenant_id) -> LifecycleTemplate:
    """Return an existing change_request LifecycleTemplate for tenant, or create one."""
    existing = (await db.execute(
        _sel(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant_id,
            LifecycleTemplate.entity_type == "change_request",
        ).limit(1)
    )).scalars().first()
    if existing:
        return existing
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="change_request", name="health-test-cr",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [], "field_permissions": {},
        },
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _booking(db, tenant_id, user_id, env_id, start, end, status="approved"):
    """Create a BookingRequest + child Booking (mirrors test_conflict_service pattern)."""
    bt = await _ensure_booking_type(db, tenant_id)
    req = BookingRequest(
        tenant_id=tenant_id, project_name="Health Test Project",
        booking_type_id=bt.id, start_date=start, end_date=end,
        booked_by=user_id, context_tag="none", exclusive_use_requested=False,
    )
    db.add(req)
    await db.flush()
    b = Booking(
        tenant_id=tenant_id, environment_id=env_id,
        booking_request_id=req.id, start_date=start, end_date=end, status=status,
    )
    db.add(b)
    await db.flush()
    return b


async def _cr_outage(db, tenant_id, user_id, env_id, o_start, o_end, has_outage=True, status="approved"):
    """Create a ChangeRequest + ChangeRequestEnvironment with outage window."""
    cr_tpl = await _ensure_cr_lifecycle(db, tenant_id)
    cr = ChangeRequest(
        tenant_id=tenant_id, title="Planned Outage CR", change_type="infrastructure",
        status=status, lifecycle_id=cr_tpl.id, has_outage=has_outage,
        outage_start=o_start, outage_end=o_end,
        scheduled_start=o_start, scheduled_end=o_end,
        raised_by=user_id,
    )
    db.add(cr)
    await db.flush()
    db.add(ChangeRequestEnvironment(
        tenant_id=tenant_id, change_request_id=cr.id, environment_id=env_id,
    ))
    await db.flush()
    return cr


@pytest.mark.asyncio
async def test_record_sample_defaults_recorded_at(db_session, tenant):
    env = await _env(db_session, tenant.id)
    row = await svc.record_sample(db_session, tenant.id, env.id, "up", "pingdom")
    assert row.status == "up" and row.source == "pingdom" and row.recorded_at is not None


@pytest.mark.asyncio
async def test_record_sample_rejects_other_tenant_env(db_session, tenant):
    with pytest.raises(HTTPException) as e:
        await svc.record_sample(db_session, tenant.id, 999999, "up", "x")
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_history_newest_first(db_session, tenant):
    env = await _env(db_session, tenant.id)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    await svc.record_sample(db_session, tenant.id, env.id, "up", "x", recorded_at=t0)
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=t0 + timedelta(minutes=5))
    hist = await svc.get_history(db_session, tenant.id, env.id)
    assert [h.status for h in hist] == ["down", "up"]


@pytest.mark.asyncio
async def test_derive_status_fresh_stale_and_none(db_session, tenant):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    env = await _env(db_session, tenant.id)
    # no samples -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "unknown"
    # fresh sample -> its status
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=now - timedelta(minutes=5))
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "down"
    # stale sample (>15m) -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now + timedelta(minutes=20))
    assert ov[0]["current_status"] == "unknown"


@pytest.mark.asyncio
async def test_alert_truth_table(db_session, tenant, user):
    """5-case alert truth table: down+booking+no outage=alert; others=no alert."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    win = (now - timedelta(hours=1), now + timedelta(hours=1))

    async def overview_for(env):
        return next(r for r in await svc.health_overview(db_session, tenant.id, now=now) if r["environment_id"] == env.id)

    # Case 1: down + active booking + no outage -> ALERT
    e1 = await _env(db_session, tenant.id, "e1")
    await svc.record_sample(db_session, tenant.id, e1.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, user.id, e1.id, *win)
    assert (await overview_for(e1))["alert"] is True

    # Case 2: down + active booking + planned outage -> no alert
    e2 = await _env(db_session, tenant.id, "e2")
    await svc.record_sample(db_session, tenant.id, e2.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, user.id, e2.id, *win)
    await _cr_outage(db_session, tenant.id, user.id, e2.id, *win)
    assert (await overview_for(e2))["alert"] is False

    # Case 3: up + active booking -> no alert
    e3 = await _env(db_session, tenant.id, "e3")
    await svc.record_sample(db_session, tenant.id, e3.id, "up", "x", recorded_at=now)
    await _booking(db_session, tenant.id, user.id, e3.id, *win)
    assert (await overview_for(e3))["alert"] is False

    # Case 4: down + NO active booking -> no alert
    e4 = await _env(db_session, tenant.id, "e4")
    await svc.record_sample(db_session, tenant.id, e4.id, "down", "x", recorded_at=now)
    assert (await overview_for(e4))["alert"] is False

    # Case 5: draft booking is not "active" -> down + draft booking -> no alert
    e5 = await _env(db_session, tenant.id, "e5")
    await svc.record_sample(db_session, tenant.id, e5.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, user.id, e5.id, *win, status="draft")
    assert (await overview_for(e5))["alert"] is False
