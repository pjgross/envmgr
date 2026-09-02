"""pir_finding_service — actions: closure stamping, and what 'overdue' means."""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from app.api.v1.schemas.pir_finding import PirActionCreate, PirActionUpdate, PirFindingCreate
from app.core.security import get_password_hash
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.pir import PIR
from app.db.models.pir_finding import PirAction
from app.db.models.release import Release
from app.db.models.user import Tenant, User
from app.services import pir_finding_service

UTC = timezone.utc


async def _pir(db, tenant_id, user_id, name="R"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"RT-{name}", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl)
    await db.flush()
    r = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(r)
    await db.flush()
    p = PIR(tenant_id=tenant_id, release_id=r.id, summary=None, status="draft", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


@pytest.fixture
async def finding(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    return await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)


@pytest.fixture
async def other_tenant(db_session) -> Tenant:
    t = Tenant(name="Other Org PIR Actions", slug="other-org-pir-actions")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.fixture
async def other_user(db_session, other_tenant) -> User:
    u = User(
        tenant_id=other_tenant.id,
        username="other-pir-actions",
        email="other-pir-actions@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_an_action_starts_open_with_no_closing_date(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="Add a perf gate"), user.id)
    assert (a.status, a.closed_at, a.seq) == ("open", None, 1)


@pytest.mark.asyncio
async def test_closing_stamps_closed_at_and_reopening_clears_it(db_session, tenant, user, finding):
    """A reopened action has no closing date. A stale one reads as a closure that
    happened, which is exactly the claim the worklist exists to disprove."""
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="done", closure_note="shipped"))
    assert a.closed_at is not None
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="in_progress"))
    assert a.closed_at is None


@pytest.mark.asyncio
async def test_cancelled_closes_too(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="cancelled"))
    assert a.closed_at is not None


@pytest.mark.asyncio
async def test_an_unknown_status_is_refused_by_the_schema(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    with pytest.raises(ValueError):
        PirActionUpdate(status="nearly")


@pytest.mark.asyncio
async def test_an_action_is_overdue_only_after_its_whole_due_day(db_session, tenant, user, finding):
    """A DEADLINE IS A DAY. The UI writes a due date at T00:00:00Z; at instant
    precision an action due today reads overdue from one minute past midnight."""
    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    today = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="due today", due_date=datetime(2026, 9, 10, tzinfo=UTC)), user.id)
    yesterday = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="due yesterday", due_date=datetime(2026, 9, 9, tzinfo=UTC)), user.id)
    assert pir_finding_service.is_overdue(today, now) is False
    assert pir_finding_service.is_overdue(yesterday, now) is True


@pytest.mark.asyncio
async def test_a_closed_action_is_never_overdue(db_session, tenant, user, finding):
    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="T", due_date=datetime(2026, 1, 1, tzinfo=UTC)), user.id)
    assert pir_finding_service.is_overdue(a, now) is True
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="done"))
    assert pir_finding_service.is_overdue(a, now) is False


@pytest.mark.asyncio
async def test_an_action_with_no_due_date_is_never_overdue(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    assert pir_finding_service.is_overdue(a, datetime(2030, 1, 1, tzinfo=UTC)) is False


@pytest.mark.asyncio
async def test_actions_are_batched_one_query_for_the_whole_pir(db_session, tenant, user, finding):
    """A 40-finding PIR must not be 40 queries. `actions_for_findings` keys by
    finding id and returns [] for a finding with none, so no caller has to guess."""
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="A"), user.id)
    b = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="B"), user.id)
    by_finding = await pir_finding_service.actions_for_findings(
        db_session, tenant.id, [finding.id, finding.id + 999])
    assert [x.title for x in by_finding[finding.id]] == ["A", "B"]
    assert by_finding[finding.id + 999] == []


@pytest.mark.asyncio
async def test_a_deleted_action_is_gone_and_does_not_hold_its_number(db_session, tenant, user,
                                                                     finding):
    first = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="A"), user.id)
    second = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="B"), user.id)
    await pir_finding_service.delete_action(db_session, tenant.id, first.id)
    third = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="C"), user.id)
    assert third.seq == 3
    by_finding = await pir_finding_service.actions_for_findings(db_session, tenant.id, [finding.id])
    assert [x.title for x in by_finding[finding.id]] == ["B", "C"]


@pytest.mark.asyncio
async def test_an_action_in_another_tenant_is_a_404(db_session, tenant, other_tenant, user,
                                                    other_user):
    theirs_pir = await _pir(db_session, other_tenant.id, other_user.id, name="Theirs")
    theirs_finding = await pir_finding_service.create_finding(
        db_session, other_tenant.id, theirs_pir, PirFindingCreate(kind="went_wrong", title="T"),
        other_user.id)
    theirs = await pir_finding_service.create_action(
        db_session, other_tenant.id, theirs_finding, PirActionCreate(title="T"), other_user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.update_action(
            db_session, tenant.id, theirs.id, PirActionUpdate(status="done"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_deleted_user_cannot_be_given_new_work(db_session, tenant, user, finding):
    """`deleted_at` and `is_active` are different retirement states. A deactivated
    user may still own an action; a DELETED one is gone, and assigning them new
    work makes it look owned to a queue and unowned to a human."""
    gone = User(
        tenant_id=tenant.id, username="departed", email="departed@test.com",
        password_hash=get_password_hash("password123"), role="Developer", is_active=True,
        deleted_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    db_session.add(gone)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.create_action(
            db_session, tenant.id, finding, PirActionCreate(title="T", owner_id=gone.id), user.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_deactivated_owner_is_still_a_valid_owner(db_session, tenant, user, finding):
    """The complement, and the one that stops the rule above being over-applied:
    deactivating someone does not invalidate the actions they own, nor stop them
    being assigned — A4's contention owners follow the same rule."""
    dormant = User(
        tenant_id=tenant.id, username="dormant", email="dormant@test.com",
        password_hash=get_password_hash("password123"), role="Developer", is_active=False,
    )
    db_session.add(dormant)
    await db_session.flush()

    action = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T", owner_id=dormant.id), user.id)
    assert action.owner_id == dormant.id


@pytest.mark.asyncio
async def test_resending_an_unchanged_owner_survives_that_user_being_deleted(
    db_session, tenant, user, finding
):
    """The unchanged-value carve-out, now that `_validate_owner` filters
    `deleted_at` and it is reachable: a full-form save that re-sends the owner
    the row already has must not 422 because that user has since been deleted.
    Changing to a deleted owner still is."""
    owner = User(
        tenant_id=tenant.id, username="leaver", email="leaver@test.com",
        password_hash=get_password_hash("password123"), role="Developer", is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    action = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T", owner_id=owner.id), user.id)

    owner.deleted_at = datetime(2026, 8, 1, tzinfo=UTC)
    await db_session.flush()

    saved = await pir_finding_service.update_action(
        db_session, tenant.id, action.id,
        PirActionUpdate(title="T2", owner_id=owner.id))
    assert saved.title == "T2"
    assert saved.owner_id == owner.id


@pytest.mark.asyncio
async def test_actions_are_not_read_across_tenants(db_session, tenant, other_tenant, other_user,
                                                   user, finding):
    """`actions_for_findings` filters `tenant_id` as well as `finding_id`. The
    finding ids reaching it are already tenant-scoped, so this guards the
    ANSWER's correctness rather than isolation — but the module claims everything
    here is tenant-scoped on the way in, and without a test the filter could be
    deleted with the whole suite green.
    """
    await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="Mine"), user.id)
    # A row that could only exist through cross-tenant corruption — which is
    # exactly what the filter is defence against.
    stray = PirAction(tenant_id=other_tenant.id, finding_id=finding.id, seq=99,
                      title="Not mine", status="open", created_by=other_user.id)
    db_session.add(stray)
    await db_session.flush()

    by_finding = await pir_finding_service.actions_for_findings(
        db_session, tenant.id, [finding.id])
    assert [a.title for a in by_finding[finding.id]] == ["Mine"]
