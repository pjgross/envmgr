"""pir_finding_service — the rules a finding carries."""
import pytest
from datetime import timezone
from fastapi import HTTPException

from app.api.v1.schemas.pir_finding import PirFindingCreate, PirFindingUpdate
from app.db.models.pir import PIR
from app.db.models.pir_finding import PirFinding
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
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


@pytest.mark.asyncio
async def test_seq_is_per_pir_and_per_kind(db_session, tenant, user):
    """Two lists on one page, each numbered from 1 — a went-wrong finding does not
    take a number away from the went-well list above it."""
    pir = await _pir(db_session, tenant.id, user.id)
    a = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="A"), user.id)
    b = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="B"), user.id)
    c = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_well", title="C"), user.id)
    assert (a.seq, b.seq, c.seq) == (1, 2, 1)


@pytest.mark.asyncio
async def test_a_deleted_finding_does_not_hold_its_number(db_session, tenant, user):
    """seq is the max of the LIVE rows plus one. Deleting #2 of three and adding
    another must not collide with the surviving #3."""
    pir = await _pir(db_session, tenant.id, user.id)
    ids = []
    for t in ("A", "B", "C"):
        f = await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title=t), user.id)
        ids.append(f.id)
    await pir_finding_service.delete_finding(db_session, tenant.id, ids[1])
    d = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="D"), user.id)
    assert d.seq == 4


@pytest.mark.asyncio
async def test_update_leaves_omitted_keys_alone_and_an_explicit_null_clears(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir,
        PirFindingCreate(kind="went_wrong", title="T", detail="D", root_cause="RC"), user.id)

    await pir_finding_service.update_finding(
        db_session, tenant.id, f.id, PirFindingUpdate(title="T2"))
    assert (f.title, f.detail, f.root_cause) == ("T2", "D", "RC")

    await pir_finding_service.update_finding(
        db_session, tenant.id, f.id, PirFindingUpdate(root_cause=None))
    assert f.root_cause is None
    assert f.detail == "D"


@pytest.mark.asyncio
async def test_kind_is_immutable_once_set(db_session, tenant, user):
    """A finding's kind is which LIST it is in. Flipping it would move an item
    between 'keep doing this' and 'this failed' while its root cause and actions
    followed it across — delete and re-raise instead."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.update_finding(
            db_session, tenant.id, f.id, PirFindingUpdate(kind="went_well"))
    assert exc.value.status_code == 422
    assert "kind" in exc.value.detail


@pytest.mark.asyncio
async def test_a_deleted_finding_is_gone_from_reads_and_from_get(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    await pir_finding_service.delete_finding(db_session, tenant.id, f.id)
    assert await pir_finding_service.findings_for_pir(db_session, tenant.id, pir.id) == []
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.get_finding(db_session, tenant.id, f.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_findings_read_back_went_well_first_then_by_seq(db_session, tenant, user):
    """The read order IS the page order, decided once on the server, so two
    surfaces cannot render the same review in two orders."""
    pir = await _pir(db_session, tenant.id, user.id)
    for kind, title in (("went_wrong", "W1"), ("went_well", "G1"), ("went_wrong", "W2"),
                        ("went_well", "G2")):
        await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind=kind, title=title), user.id)
    rows = await pir_finding_service.findings_for_pir(db_session, tenant.id, pir.id)
    assert [r.title for r in rows] == ["G1", "G2", "W1", "W2"]


@pytest.mark.asyncio
async def test_a_finding_in_another_tenant_is_a_404_not_someone_elses_row(db_session, tenant, user):
    """Mutation check: drop the tenant_id filter in get_finding and this test must
    fail. The missing tenant filter appeared eight times on A1 and no pre-existing
    test caught one of them."""
    from app.core.security import get_password_hash
    from app.db.models.user import Tenant, User

    other_tenant = Tenant(name="Other Org", slug="other-org-pir-findings")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        username="other-pir-findings",
        email="other-pir-findings@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    theirs = await _pir(db_session, other_tenant.id, other_user.id, name="Theirs")
    f = await pir_finding_service.create_finding(
        db_session, other_tenant.id, theirs, PirFindingCreate(kind="went_wrong", title="T"),
        other_user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.get_finding(db_session, tenant.id, f.id)
    assert exc.value.status_code == 404
