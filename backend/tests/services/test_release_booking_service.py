"""Tests for release_booking_service + booking context_tag derivation."""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.user import Tenant
from app.services import release_booking_service
from app.services.booking_service import derive_and_set_context_tag


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_booking_type(db_session, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="booking",
        name="default",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()

    bt = BookingType(tenant_id=tenant_id, name="Standard", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.flush()
    return bt


async def _make_release_lifecycle(db_session, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Major",
        is_default=True,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _make_release(db_session, tenant_id, user_id):
    tpl = await _make_release_lifecycle(db_session, tenant_id)
    release = Release(
        tenant_id=tenant_id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _make_environment(db_session, tenant_id):
    env = Environment(
        tenant_id=tenant_id, name="SIT env", environment_type="test"
    )
    db_session.add(env)
    await db_session.flush()
    return env


async def _make_system(db_session, tenant_id):
    sys = System(tenant_id=tenant_id, name="Core API")
    db_session.add(sys)
    await db_session.flush()
    return sys


# ── test_book_for_phase_creates_booking_with_release_and_phase_set ─────────

@pytest.mark.asyncio
async def test_book_for_phase_creates_booking_with_release_and_phase_set(
    db_session, tenant, user
):
    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)

    now = datetime.now(timezone.utc)
    booking = await release_booking_service.book_environment_for_phase(
        db_session,
        release_id=release.id,
        phase_id=None,
        environment_id=env.id,
        start=now + timedelta(days=1),
        end=now + timedelta(days=5),
        booking_type_id=bt.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )
    assert booking.release_id == release.id
    assert booking.test_phase_id is None


# ── test_derive_context_tag_deployment_role ──────────────────────────────────

@pytest.mark.asyncio
async def test_derive_context_tag_deployment_role(db_session, tenant, user):
    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)
    sys = await _make_system(db_session, tenant.id)

    # Link system to environment
    db_session.add(EnvironmentSystem(
        environment_id=env.id, system_id=sys.id, tenant_id=tenant.id
    ))
    # Link system to release with role='changing'
    db_session.add(ReleaseSystem(
        tenant_id=tenant.id, release_id=release.id, system_id=sys.id, role="changing"
    ))
    await db_session.flush()

    now = datetime.now(timezone.utc)
    booking = await release_booking_service.book_environment_for_phase(
        db_session,
        release_id=release.id,
        phase_id=None,
        environment_id=env.id,
        start=now + timedelta(days=1),
        end=now + timedelta(days=5),
        booking_type_id=bt.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )

    br = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
        )
    ).scalar_one()
    assert br.context_tag == ContextTag.DEPLOYMENT


# ── test_derive_context_tag_regression_role ──────────────────────────────────

@pytest.mark.asyncio
async def test_derive_context_tag_regression_role(db_session, tenant, user):
    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)
    sys = await _make_system(db_session, tenant.id)

    db_session.add(EnvironmentSystem(
        environment_id=env.id, system_id=sys.id, tenant_id=tenant.id
    ))
    db_session.add(ReleaseSystem(
        tenant_id=tenant.id, release_id=release.id, system_id=sys.id, role="regression"
    ))
    await db_session.flush()

    now = datetime.now(timezone.utc)
    booking = await release_booking_service.book_environment_for_phase(
        db_session,
        release_id=release.id,
        phase_id=None,
        environment_id=env.id,
        start=now + timedelta(days=1),
        end=now + timedelta(days=5),
        booking_type_id=bt.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )

    br = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
        )
    ).scalar_one()
    assert br.context_tag == ContextTag.REGRESSION


# ── test_derive_context_tag_no_release_system_match_yields_none ──────────────

@pytest.mark.asyncio
async def test_derive_context_tag_no_release_system_match_yields_none(
    db_session, tenant, user
):
    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)
    sys = await _make_system(db_session, tenant.id)

    # Link system to environment but NOT to release
    db_session.add(EnvironmentSystem(
        environment_id=env.id, system_id=sys.id, tenant_id=tenant.id
    ))
    await db_session.flush()

    now = datetime.now(timezone.utc)
    booking = await release_booking_service.book_environment_for_phase(
        db_session,
        release_id=release.id,
        phase_id=None,
        environment_id=env.id,
        start=now + timedelta(days=1),
        end=now + timedelta(days=5),
        booking_type_id=bt.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )

    br = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
        )
    ).scalar_one()
    assert br.context_tag == ContextTag.NONE


# ── test_update_booking_re_derives_context_tag ────────────────────────────────

@pytest.mark.asyncio
async def test_update_booking_re_derives_context_tag(db_session, tenant, user):
    """derive_and_set_context_tag updates correctly when called after booking creation."""
    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)
    sys = await _make_system(db_session, tenant.id)

    db_session.add(EnvironmentSystem(
        environment_id=env.id, system_id=sys.id, tenant_id=tenant.id
    ))
    # Initially no release_system — should get NONE
    await db_session.flush()

    now = datetime.now(timezone.utc)
    booking = await release_booking_service.book_environment_for_phase(
        db_session,
        release_id=release.id,
        phase_id=None,
        environment_id=env.id,
        start=now + timedelta(days=1),
        end=now + timedelta(days=5),
        booking_type_id=bt.id,
        tenant_id=tenant.id,
        user_id=user.id,
    )

    br = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
        )
    ).scalar_one()
    assert br.context_tag == ContextTag.NONE

    # Now add release_system with 'changing' and re-derive
    db_session.add(ReleaseSystem(
        tenant_id=tenant.id, release_id=release.id, system_id=sys.id, role="changing"
    ))
    await db_session.flush()

    await derive_and_set_context_tag(db_session, booking.id, tenant.id)

    await db_session.refresh(br)
    assert br.context_tag == ContextTag.DEPLOYMENT


# ── test_tenant_isolation_cannot_book_other_tenants_release ──────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_cannot_book_other_tenants_release(
    db_session, tenant, user
):
    from fastapi import HTTPException
    tenant_b = Tenant(name="Other Co", slug="other-co")
    db_session.add(tenant_b)
    await db_session.flush()

    bt = await _make_booking_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)
    env = await _make_environment(db_session, tenant.id)

    now = datetime.now(timezone.utc)
    with pytest.raises(HTTPException) as exc_info:
        await release_booking_service.book_environment_for_phase(
            db_session,
            release_id=release.id,
            phase_id=None,
            environment_id=env.id,
            start=now + timedelta(days=1),
            end=now + timedelta(days=5),
            booking_type_id=bt.id,
            tenant_id=tenant_b.id,  # Wrong tenant
            user_id=user.id,
        )
    assert exc_info.value.status_code == 404
