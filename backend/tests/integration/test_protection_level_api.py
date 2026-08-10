"""Phase 7 B4 — the protection level end to end.

B4 ADVISES. Nothing here may assert that a booking was refused, moved or
cancelled because of a protection level; `test_b4_advises_never_blocks.py`
holds the guard on that.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.protection_levels import (
    PROTECTION_HARD,
    PROTECTION_LEVELS,
    PROTECTION_SOFT,
)
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.lifecycle import LifecycleTemplate
from tests.factories import ensure_booking_type

# ── Local fixtures ───────────────────────────────────────────────────────────
# `tenant` and `user` come from tests/conftest.py. This repo has no
# repo-wide `lifecycle_template` or `booking_type` fixture — every module
# that needs one defines it locally (see test_release_happy_path.py) — so
# this module follows the same pattern rather than inventing shared fixtures.


@pytest_asyncio.fixture(scope="function")
async def lifecycle_template(db_session, tenant) -> LifecycleTemplate:
    """A minimal booking lifecycle template for `tenant`."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="booking",
        name="protection-level-test-lifecycle",
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
    await db_session.refresh(tpl)
    return tpl


@pytest_asyncio.fixture(scope="function")
async def booking_type(db_session, tenant) -> BookingType:
    """A real BookingType for `tenant`, via the shared FK helper (it creates
    its own lifecycle template, distinct from the one above)."""
    return await ensure_booking_type(db_session, tenant.id)


def test_the_two_levels_are_the_whole_vocabulary():
    assert PROTECTION_LEVELS == {PROTECTION_SOFT, PROTECTION_HARD}
    assert PROTECTION_SOFT == "soft"
    assert PROTECTION_HARD == "hard"


@pytest.mark.asyncio
async def test_a_new_booking_type_defaults_to_soft(db_session, tenant, lifecycle_template):
    bt = BookingType(
        tenant_id=tenant.id,
        name="Ad hoc",
        lifecycle_template_id=lifecycle_template.id,
    )
    db_session.add(bt)
    await db_session.flush()
    await db_session.refresh(bt)
    assert bt.default_protection_level == PROTECTION_SOFT
    # Null means "this type has no preset" — a legitimate state, not a
    # missing value, the same call B1 made for environment.expires_at.
    assert bt.default_duration_minutes is None


@pytest.mark.asyncio
async def test_a_new_request_defaults_to_soft(db_session, tenant, booking_type, user):
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=tenant.id,
        project_name="Regression",
        booking_type_id=booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        booked_by=user.id,
    )
    db_session.add(req)
    await db_session.flush()
    await db_session.refresh(req)
    assert req.protection_level == PROTECTION_SOFT

    stored = (await db_session.execute(
        select(BookingRequest.protection_level).where(BookingRequest.id == req.id)
    )).scalar_one()
    assert stored == PROTECTION_SOFT
