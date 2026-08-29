"""The three tables PIR findings hang off, and the invariants their columns carry."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.pir import PIR
from app.db.models.pir_finding import (
    ACTION_STATUSES,
    CLOSED_ACTION_STATUSES,
    FINDING_KINDS,
    PirAction,
    PirFinding,
    PirFindingIncident,
)
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.incident import Incident

UTC = timezone.utc


async def _release(db, tenant_id: int, user_id: int) -> Release:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="RT-models", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl)
    await db.flush()
    r = Release(tenant_id=tenant_id, name="R-models", release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(r)
    await db.flush()
    return r


async def _pir(db, tenant_id: int, user_id: int) -> PIR:
    r = await _release(db, tenant_id, user_id)
    p = PIR(tenant_id=tenant_id, release_id=r.id, summary="s", status="draft", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_vocabularies_are_what_the_spec_says():
    assert FINDING_KINDS == {"went_well", "went_wrong"}
    assert ACTION_STATUSES == {"open", "in_progress", "done", "cancelled"}
    assert CLOSED_ACTION_STATUSES == {"done", "cancelled"}


@pytest.mark.asyncio
async def test_a_finding_persists_with_its_root_cause(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1,
                   title="No load test before go-live", detail="d",
                   root_cause="Perf gate is optional", created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    got = (await db_session.execute(select(PirFinding).where(PirFinding.id == f.id))).scalar_one()
    assert (got.kind, got.seq, got.root_cause) == ("went_wrong", 1, "Perf gate is optional")
    assert got.deleted_at is None
    assert got.created_at is not None and got.updated_at is not None


@pytest.mark.asyncio
async def test_a_went_well_finding_may_carry_a_root_cause_and_an_action(db_session, tenant, user):
    """Nothing REFUSES a root cause on a went-well finding, and an action may hang off one:
    'codify this in the release template' is a real PIR outcome."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_well", seq=1,
                   title="Canary caught it", root_cause="Canary ran for 30 minutes",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    a = PirAction(tenant_id=tenant.id, finding_id=f.id, seq=1, title="Codify canary in the template",
                  status="open", created_by=user.id)
    db_session.add(a)
    await db_session.flush()
    assert a.id is not None


@pytest.mark.asyncio
async def test_an_action_defaults_to_open_and_holds_owner_and_due_date(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1, title="t",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    due = datetime(2026, 9, 30, tzinfo=UTC)
    a = PirAction(tenant_id=tenant.id, finding_id=f.id, seq=1, title="Add a perf gate",
                  owner_id=user.id, due_date=due, created_by=user.id)
    db_session.add(a)
    await db_session.flush()
    got = (await db_session.execute(select(PirAction).where(PirAction.id == a.id))).scalar_one()
    assert got.status == "open"
    assert got.owner_id == user.id
    assert got.closed_at is None and got.closure_note is None


@pytest.mark.asyncio
async def test_one_incident_cites_one_finding_only_once(db_session, tenant, user):
    """uq_pir_finding_incident. The citation is a fact, not a counter."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1, title="t",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db_session.add(inc)
    await db_session.flush()

    db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id, incident_id=inc.id,
                                      note="first"))
    await db_session.flush()
    db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id, incident_id=inc.id,
                                      note="again"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_one_incident_may_cite_two_findings(db_session, tenant, user):
    """One incident often exposes two distinct process failures — neither direction is 1:1."""
    pir = await _pir(db_session, tenant.id, user.id)
    findings = []
    for seq in (1, 2):
        f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=seq,
                       title=f"failure {seq}", created_by=user.id)
        db_session.add(f)
        findings.append(f)
    await db_session.flush()
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db_session.add(inc)
    await db_session.flush()
    for f in findings:
        db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id,
                                          incident_id=inc.id))
    await db_session.flush()
    rows = (await db_session.execute(
        select(PirFindingIncident).where(PirFindingIncident.incident_id == inc.id))).scalars().all()
    assert len(rows) == 2
