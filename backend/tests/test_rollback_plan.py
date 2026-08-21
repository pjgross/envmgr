"""Phase 9 C4 Task 2 — rollback plan CRUD (service layer).

Covers the upsert-not-duplicate rule, the written-vs-agreed distinction, and
the two 404s (system outside the release, release outside the tenant).
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.v1.schemas.rollback import RollbackPlanCreate
from app.core.security import get_password_hash
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.user import Tenant, User
from app.services import rollback_plan_service


# ── Shared fixtures — follows backend/tests/test_release_gate_typing.py ──────

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
    other_tenant = Tenant(name="Other Org", slug="other-org-rollback")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        username="other-org-admin",
        email="admin@other-org-rollback.com",
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
async def test_a_plan_is_upserted_per_release_and_system(
    db_session, test_tenant, test_user, release, system
):
    first = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="Redeploy previous artefact",
                           reversibility="reversible"),
    )
    second = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="Redeploy, then replay the queue",
                           reversibility="lossy"),
    )
    assert first.id == second.id, "a second write for the same pair must update, not duplicate"
    assert second.steps == "Redeploy, then replay the queue"
    assert second.reversibility == "lossy"


@pytest.mark.asyncio
async def test_a_written_plan_is_not_an_agreed_plan(
    db_session, test_tenant, test_user, release, system
):
    """'Written' and 'agreed' are two states. An unagreed draft is legitimate."""
    plan = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
    )
    assert plan.agreed_by_user_id is None and plan.agreed_at is None

    agreed = await rollback_plan_service.agree_plan(
        db_session, plan.id, test_tenant.id, test_user.id
    )
    assert agreed.agreed_by_user_id == test_user.id
    assert agreed.agreed_at is not None


@pytest.mark.asyncio
async def test_a_system_outside_the_release_is_refused(
    db_session, test_tenant, test_user, release, unrelated_system
):
    """A plan may only name a system the release actually touches."""
    with pytest.raises(HTTPException) as exc:
        await rollback_plan_service.upsert_plan(
            db_session, release.id, test_tenant.id, test_user.id,
            RollbackPlanCreate(system_id=unrelated_system.id, steps="s",
                               reversibility="reversible"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_refused(
    db_session, test_tenant, test_user, other_tenant_release, system
):
    """The 404 here must come from the tenant filter on the release lookup,
    not from the (also-404) release_system membership check — so `system` is
    attached to `other_tenant_release` too, meaning the membership check
    alone would let this call through and only the tenant filter can refuse
    it. Without this, a mutation that deletes the tenant filter passes this
    test vacuously (proved: it did, on the first draft of this test)."""
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
        await rollback_plan_service.upsert_plan(
            db_session, other_tenant_release.id, test_tenant.id, test_user.id,
            RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_listing_plans_for_another_tenants_release_is_refused(
    db_session, test_tenant, other_tenant_release
):
    """list_plans must run the same tenant-qualified release lookup as
    upsert_plan — a release id from another tenant is not-found, not empty."""
    with pytest.raises(HTTPException) as exc:
        await rollback_plan_service.list_plans(
            db_session, other_tenant_release.id, test_tenant.id
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_reversibility_is_rejected_by_the_schema():
    with pytest.raises(Exception):
        RollbackPlanCreate(system_id=1, steps="s", reversibility="probably_fine")


@pytest.mark.asyncio
async def test_editing_an_agreed_plan_clears_the_agreement(
    db_session, test_tenant, test_user, release, system
):
    """A plan a sponsor agreed to and someone then rewrote is not the plan
    they agreed to — editing steps or reversibility clears the agreement."""
    plan = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
    )
    await rollback_plan_service.agree_plan(db_session, plan.id, test_tenant.id, test_user.id)

    edited = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s, revised", reversibility="reversible"),
    )
    assert edited.agreed_by_user_id is None
    assert edited.agreed_at is None


@pytest.mark.asyncio
async def test_plans_for_releases_is_a_batch_lookup(
    db_session, test_tenant, test_user, release, system
):
    await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
    )
    by_release = await rollback_plan_service.plans_for_releases(
        db_session, test_tenant.id, [release.id]
    )
    assert list(by_release.keys()) == [release.id]
    assert len(by_release[release.id]) == 1


@pytest.mark.asyncio
async def test_delete_plan_soft_deletes(
    db_session, test_tenant, test_user, release, system
):
    plan = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
    )
    await rollback_plan_service.delete_plan(db_session, plan.id, test_tenant.id)
    remaining = await rollback_plan_service.list_plans(db_session, release.id, test_tenant.id)
    assert remaining == []
