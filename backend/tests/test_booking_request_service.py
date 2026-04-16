import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.services import booking_request_service
from app.db.models.environment import Environment
from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType


async def _seed_lifecycle_and_type(db_session, tenant):
    tpl = BookingLifecycleTemplate(
        tenant_id=tenant.id,
        name="default",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
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
    return bt


async def _make_env(db_session, tenant, name):
    env = Environment(tenant_id=tenant.id, name=name, environment_type="dev")
    db_session.add(env)
    await db_session.flush()
    return env


@pytest.mark.asyncio
async def test_create_request_with_multiple_envs(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    req, detected = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "p",
            "booking_type_id": bt.id,
            "start_date": t0,
            "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id, env_b.id],
            "notes": None,
            "context_tag": "none",
            "exclusive_use_requested": False,
            "custom_fields": None,
            "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    assert req.id is not None
    assert len(req.bookings) == 2
    assert {b.environment_id for b in req.bookings} == {env_a.id, env_b.id}
    assert all(b.status == "draft" for b in req.bookings)
    assert all(b.start_date == t0 for b in req.bookings)
    assert detected == {}


@pytest.mark.asyncio
async def test_create_request_rejects_duplicate_envs(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as exc:
        await booking_request_service.create_request(
            db_session,
            data={
                "project_name": "p",
                "booking_type_id": bt.id,
                "start_date": t0,
                "end_date": t0 + timedelta(days=2),
                "environment_ids": [env_a.id, env_a.id],
                "notes": None,
                "context_tag": "none",
                "exclusive_use_requested": False,
                "custom_fields": None,
                "delegate_user_ids": None,
            },
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_request_reports_detected_conflicts(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    _, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "old",
            "booking_type_id": bt.id,
            "start_date": t0,
            "end_date": t0 + timedelta(days=5),
            "environment_ids": [env_a.id],
            "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    new_req, detected = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "new",
            "booking_type_id": bt.id,
            "start_date": t0 + timedelta(days=1),
            "end_date": t0 + timedelta(days=3),
            "environment_ids": [env_a.id],
            "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    assert new_req.id is not None
    assert env_a.id in {booking.environment_id for booking in new_req.bookings}
    new_child = next(b for b in new_req.bookings if b.environment_id == env_a.id)
    assert new_child.id in detected
    assert len(detected[new_child.id]) == 1
