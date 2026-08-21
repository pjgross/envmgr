"""Phase 9 C4 Task 6 — rollback authorisation: the record of a rollback

decision, raisable BEFORE OR AFTER the fact.

C4 must never stand between a team and a 2am recovery. This service validates
ids only — the release must be in the caller's tenant, and every system id
named must appear on that release's release_system rows — and inspects
NOTHING about plan state, rehearsal state or the readiness verdict. A
rollback with no plan at all is exactly the case worth recording.
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.v1.schemas.rollback import RollbackAuthorisationCreate
from app.core.security import get_password_hash
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.rollback import ReleaseRollbackAuthorisation
from app.db.models.system import System
from app.db.models.user import Tenant, User
from app.services import rollback_authorisation_service


# ── Shared fixtures — follows backend/tests/test_rollback_plan.py ────────────
# Deliberately NOT the global `system` fixture in conftest.py: that one is
# built against the `tenant` fixture, not `test_tenant`, and this file's
# cross-tenant-shaped scenarios need a system whose tenant matches
# `test_tenant` exactly so an exclusion could actually be observed.

def _release_lifecycle(tenant_id: int) -> LifecycleTemplate:
    return LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    template = _release_lifecycle(test_tenant.id)
    db_session.add(template)
    await db_session.flush()
    r = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


@pytest_asyncio.fixture
async def system(db_session, test_tenant, release) -> System:
    s = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(s)
    await db_session.flush()
    db_session.add(
        ReleaseSystem(
            tenant_id=test_tenant.id,
            release_id=release.id,
            system_id=s.id,
            role="changing",
        )
    )
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def unrelated_system(db_session, test_tenant) -> System:
    """Same tenant as `release`, but deliberately NOT attached to it via
    release_system — so a 404 on this fixture can only come from the
    membership check, never the tenant filter."""
    s = System(tenant_id=test_tenant.id, name="Unrelated System")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def other_tenant_release(db_session) -> Release:
    other_tenant = Tenant(name="Other Org", slug="other-org-rollback-auth")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        username="other-org-admin-ra",
        email="admin@other-org-rollback-auth.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()
    template = _release_lifecycle(other_tenant.id)
    db_session.add(template)
    await db_session.flush()
    r = Release(
        tenant_id=other_tenant.id,
        name="Other Org Release",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=other_user.id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_authorisation_can_be_recorded_with_no_plan_in_sight(
    db_session, test_tenant, test_user, release, system
):
    """C4 must never stand between a team and a 2am recovery. A rollback that
    happened is recorded whether or not anyone had written a plan."""
    auth = await rollback_authorisation_service.record_authorisation(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackAuthorisationCreate(
            decided_at=datetime(2026, 8, 21, 2, 14, tzinfo=timezone.utc),
            trigger="Checkout error rate above 5% for 10 minutes",
            rationale="Reverting to the previous build while we investigate",
            system_ids=[system.id],
        ),
    )
    assert auth.id is not None
    assert auth.system_ids == [system.id]


@pytest.mark.asyncio
async def test_it_can_be_recorded_after_the_fact(
    db_session, test_tenant, test_user, release, system
):
    """decided_at is caller-supplied and may be in the past — the record is an
    audit trail, not permission."""
    yesterday = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    auth = await rollback_authorisation_service.record_authorisation(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackAuthorisationCreate(decided_at=yesterday, trigger="t", rationale="r",
                                    system_ids=[system.id]),
    )
    assert auth.decided_at == yesterday


@pytest.mark.asyncio
async def test_a_system_the_release_never_touched_is_refused(
    db_session, test_tenant, test_user, release, unrelated_system
):
    with pytest.raises(HTTPException) as exc:
        await rollback_authorisation_service.record_authorisation(
            db_session, release.id, test_tenant.id, test_user.id,
            RollbackAuthorisationCreate(decided_at=datetime.now(timezone.utc),
                                        trigger="t", rationale="r",
                                        system_ids=[unrelated_system.id]),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_empty_system_list_is_refused(
    db_session, test_tenant, test_user, release
):
    """A rollback of nothing is not a rollback."""
    with pytest.raises(Exception):
        RollbackAuthorisationCreate(decided_at=datetime.now(timezone.utc),
                                    trigger="t", rationale="r", system_ids=[])


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_refused(
    db_session, test_tenant, test_user, other_tenant_release, system
):
    """The 404 here must come from the tenant filter on the release lookup,
    not from the (also-404) release_system membership check — so `system` is
    attached to `other_tenant_release` too, meaning the membership check
    alone would let this call through and only the tenant filter can refuse
    it. Without this, a mutation that deletes the tenant filter passes this
    test vacuously."""
    db_session.add(
        ReleaseSystem(
            tenant_id=other_tenant_release.tenant_id,
            release_id=other_tenant_release.id,
            system_id=system.id,
            role="changing",
        )
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await rollback_authorisation_service.record_authorisation(
            db_session, other_tenant_release.id, test_tenant.id, test_user.id,
            RollbackAuthorisationCreate(decided_at=datetime.now(timezone.utc),
                                        trigger="t", rationale="r",
                                        system_ids=[system.id]),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_listing_authorisations_for_another_tenants_release_is_refused(
    db_session, test_tenant, other_tenant_release
):
    """list_authorisations must run the same tenant-qualified release lookup
    as record_authorisation — a release id from another tenant is
    not-found, not empty."""
    with pytest.raises(HTTPException) as exc:
        await rollback_authorisation_service.list_authorisations(
            db_session, other_tenant_release.id, test_tenant.id
        )
    assert exc.value.status_code == 404


# ── Finding 9 — tenant-filter probes committed as tests ──────────────────────
# Committed versions of the probes the final review threw away after
# confirming each was load-bearing by mutation.

@pytest_asyncio.fixture
async def other_tenant(db_session) -> Tenant:
    t = Tenant(name="Other Org Q14", slug="other-org-rollback-auth-q14")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.mark.asyncio
async def test_list_authorisations_excludes_a_row_whose_tenant_id_does_not_match_the_caller(
    db_session, test_tenant, test_user, release, system, other_tenant
):
    """Q14: list_authorisations' auth.tenant_id filter. release_id alone
    cannot leak an authorisation across tenants in normal operation (a
    release belongs to exactly one tenant), so — following the same
    construction as Q3/Q7 in test_rollback_plan.py — this builds the row
    directly on the SAME release_id with a DIFFERENT tenant_id."""
    await rollback_authorisation_service.record_authorisation(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackAuthorisationCreate(
            decided_at=datetime.now(timezone.utc), trigger="t", rationale="r",
            system_ids=[system.id],
        ),
    )
    foreign = ReleaseRollbackAuthorisation(
        tenant_id=other_tenant.id,
        release_id=release.id,
        decided_by_user_id=test_user.id,
        decided_at=datetime.now(timezone.utc),
        trigger="foreign trigger",
        rationale="foreign rationale",
        system_ids=[system.id],
    )
    db_session.add(foreign)
    await db_session.flush()

    authorisations = await rollback_authorisation_service.list_authorisations(
        db_session, release.id, test_tenant.id
    )
    assert foreign.id not in [a.id for a in authorisations]


@pytest.mark.asyncio
async def test_get_system_names_excludes_a_system_in_another_tenant(
    db_session, test_tenant, other_tenant
):
    """Q15: rollback_authorisation_service.get_system_names' System.tenant_id
    filter — a system id belonging to another tenant must resolve to
    nothing, not that tenant's real name."""
    foreign_system = System(tenant_id=other_tenant.id, name="Other Tenant's System")
    db_session.add(foreign_system)
    await db_session.flush()

    names = await rollback_authorisation_service.get_system_names(
        db_session, {foreign_system.id}, test_tenant.id
    )
    assert foreign_system.id not in names
