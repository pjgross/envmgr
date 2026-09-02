"""pir_finding_service — citing an incident as evidence that a process failed.

The PIR fixes the process that let the incident reach production. It does not
fix the incident, and it does not own it.
"""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.schemas.pir_finding import PirActionCreate, PirFindingCreate
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.pir import PIR
from app.db.models.release import Release
from app.core.security import get_password_hash
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


async def _incident(db, tenant_id, title="Checkout 500s"):
    inc = Incident(tenant_id=tenant_id, title=title, severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db.add(inc)
    await db.flush()
    return inc


@pytest.fixture
async def other_tenant(db_session) -> Tenant:
    t = Tenant(name="Other Org PIR Citations", slug="other-org-pir-citations")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest.fixture
async def other_user(db_session, other_tenant) -> User:
    u = User(
        tenant_id=other_tenant.id,
        username="other-pir-citations",
        email="other-pir-citations@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_citing_twice_is_idempotent_not_a_duplicate(db_session, tenant, user):
    """The citation is a fact, not a counter. Re-citing returns the existing row
    and updates its note rather than raising an IntegrityError at the browser."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    first = await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "first")
    second = await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "second")
    assert first.id == second.id
    assert second.note == "second"


@pytest.mark.asyncio
async def test_an_incident_from_another_tenant_cannot_be_cited(db_session, tenant, other_tenant,
                                                               user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    theirs = await _incident(db_session, other_tenant.id, title="Theirs")
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.add_citation(db_session, tenant.id, f, theirs.id, None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_removing_a_citation_hard_deletes_it(db_session, tenant, user):
    from app.db.models.pir_finding import PirFindingIncident
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await pir_finding_service.remove_citation(db_session, tenant.id, f.id, inc.id)
    rows = (await db_session.execute(select(PirFindingIncident))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_removing_a_citation_that_is_not_there_is_a_404(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.remove_citation(db_session, tenant.id, f.id, inc.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_incidents_citations_name_the_release_and_count_open_actions(db_session, tenant,
                                                                              user):
    """Every fact the incident page renders travels WITH the row — the release's
    NAME, not its id, and the open-action count, so the reader can see whether
    the process fix is done without opening the release."""
    pir = await _pir(db_session, tenant.id, user.id, name="Release 24.3")
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir,
        PirFindingCreate(kind="went_wrong", title="No load test", root_cause="Gate optional"),
        user.id)
    done = await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="A", status="done"), user.id)
    await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="B"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "root incident")

    rows = await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id)
    assert len(rows) == 1
    row = rows[0]
    assert row["release_name"] == "Release 24.3"
    assert row["finding_title"] == "No load test"
    assert row["root_cause"] == "Gate optional"
    assert (row["action_count"], row["open_action_count"]) == (2, 1)
    assert row["pir_status"] == "draft"
    assert row["note"] == "root incident"
    assert done.status == "done"


@pytest.mark.asyncio
async def test_a_deleted_finding_stops_citing_the_incident(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await pir_finding_service.delete_finding(db_session, tenant.id, f.id)
    assert await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id) == []


@pytest.mark.asyncio
async def test_review_status_is_complete_if_any_citing_pir_is_complete(db_session, tenant, user):
    """One incident, two PIRs. 'Reviewed' is answered by the best answer available,
    not by whichever row sorts first."""
    inc = await _incident(db_session, tenant.id)
    for name, status_ in (("R-draft", "draft"), ("R-done", "complete")):
        pir = await _pir(db_session, tenant.id, user.id, name=name)
        pir.status = status_
        f = await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
        await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await db_session.flush()
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {inc.id: "complete"}


@pytest.mark.asyncio
async def test_an_uncited_incident_is_absent_from_the_status_map(db_session, tenant, user):
    """Absent, not 'none' — the caller supplies the default, so one place decides
    what an unreviewed incident is called."""
    inc = await _incident(db_session, tenant.id)
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {}


@pytest.mark.asyncio
async def test_a_later_draft_review_does_not_unset_complete(db_session, tenant, user):
    """The order-reversed twin of the test above, and the one that actually
    guards the rule: with the complete PIR cited FIRST, an unconditional
    last-row-wins fold answers 'draft' and the incident reads as unreviewed
    while a finished review of it exists. Both orders are pinned because the
    rows come back in no guaranteed order.
    """
    inc = await _incident(db_session, tenant.id)
    for name, status_ in (("R-done", "complete"), ("R-draft", "draft")):
        pir = await _pir(db_session, tenant.id, user.id, name=name)
        pir.status = status_
        f = await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
        await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await db_session.flush()
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {inc.id: "complete"}


@pytest.mark.asyncio
async def test_a_deleted_review_is_not_a_review(db_session, tenant, user):
    """A withdrawn finding stops answering for the incident on the LIST column
    too, not only on the detail panel — the two must not disagree about whether
    an incident has been reviewed.
    """
    inc = await _incident(db_session, tenant.id)
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await pir_finding_service.delete_finding(db_session, tenant.id, f.id)
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {}


@pytest.mark.asyncio
async def test_another_tenants_citation_is_neither_read_nor_removable(db_session, tenant,
                                                                     other_tenant, other_user,
                                                                     user):
    """The tenant filters on the citation reads are load-bearing, not defence in
    depth: the incident id is the caller's own, and without them one tenant's
    incident page renders another tenant's review of it.
    """
    from app.db.models.pir_finding import PirFindingIncident
    other_user_id = other_user.id
    pir = await _pir(db_session, other_tenant.id, other_user_id, name="Theirs")
    f = await pir_finding_service.create_finding(
        db_session, other_tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"),
        other_user_id)
    inc = await _incident(db_session, other_tenant.id, title="Their incident")
    await pir_finding_service.add_citation(db_session, other_tenant.id, f, inc.id, None)

    # Asked as OUR tenant, about an id we should not be able to see through.
    assert await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id) == []
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {}
    assert await pir_finding_service.citations_for_findings(
        db_session, tenant.id, [f.id]) == {f.id: []}
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.remove_citation(db_session, tenant.id, f.id, inc.id)
    assert exc.value.status_code == 404
    still_there = (await db_session.execute(
        select(PirFindingIncident))).scalars().all()
    assert len(still_there) == 1


@pytest.mark.asyncio
async def test_a_deleted_pir_stops_citing_the_incident(db_session, tenant, user):
    """A whole review can be withdrawn, not just one finding — and the incident
    page must stop showing it either way. The finding rows survive a soft-deleted
    PIR untouched, so only the PIR-side filter catches this one.
    """
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    pir.deleted_at = datetime(2026, 8, 2, tzinfo=UTC)
    await db_session.flush()
    assert await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id) == []
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {}


@pytest.mark.asyncio
async def test_a_deleted_action_is_counted_in_neither_total(db_session, tenant, user):
    """The counts are of LIVE actions. A deleted one inflating the total tells
    the incident's reader there is more process fix on record than there is, and
    inflating the open count keeps a finished finding looking unfinished.
    """
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    kept = await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="kept"), user.id)
    binned = await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="binned"), user.id)
    await pir_finding_service.delete_action(db_session, tenant.id, binned.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)

    row = (await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id))[0]
    assert (row["action_count"], row["open_action_count"]) == (1, 1)
    assert kept.deleted_at is None


@pytest.mark.asyncio
async def test_the_status_map_answers_only_for_cited_incidents(db_session, tenant, user):
    """The batched form: one query for a whole page of incidents, answering for
    the ones a review cites and staying silent about the rest — including an id
    that does not exist at all, which must not raise or invent an entry.

    (Inherited from `test_pir_service.test_pir_status_for_incidents_bulk`, whose
    subject moved here when `pirbackfill` retired `PIR.incident_id`.)
    """
    cited = await _incident(db_session, tenant.id, title="Cited")
    uncited = await _incident(db_session, tenant.id, title="Uncited")
    pir = await _pir(db_session, tenant.id, user.id)
    pir.status = "complete"
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, cited.id, None)
    await db_session.flush()

    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [cited.id, uncited.id, 999999]) == {cited.id: "complete"}


@pytest.mark.asyncio
async def test_a_soft_deleted_release_still_names_itself_on_its_citations(db_session, tenant,
                                                                          user):
    """The read-rendering rule, and the half of `citations_for_incident`'s own
    comment that had no test: the finding and PIR joins filter `deleted_at`
    because a withdrawn review is not evidence, but the RELEASE join deliberately
    does not — an archived release still renders its name on the citation that
    references it. Without this, adding `Release.deleted_at.is_(None)` to that
    join passes every other test in the file.
    """
    from sqlalchemy import update as sa_update
    from app.db.models.release import Release as ReleaseModel

    pir = await _pir(db_session, tenant.id, user.id, name="Archived Release")
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await db_session.execute(sa_update(ReleaseModel)
                             .where(ReleaseModel.id == pir.release_id)
                             .values(deleted_at=datetime(2026, 8, 2, tzinfo=UTC)))
    await db_session.flush()

    rows = await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id)
    assert [r["release_name"] for r in rows] == ["Archived Release"]
