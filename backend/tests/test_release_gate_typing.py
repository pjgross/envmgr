"""Task 6b — the write path for ReleaseGate.gate_type_id / test_phase_id.

Plan defect #5: Tasks 1-6 gave gate_type a vocabulary, a CRUD API and an
evaluator that reads a gate's type, but ReleaseGateCreate/Update never
carried the field. This file guards the write path that closes that hole:
the FK validation (tenant-scoped, with the archived-value carve-out an
update path always needs), the exclude_unset semantics, and the fact that
typing a gate actually changes what the evaluator reports.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateUpdate
from app.core.security import get_password_hash
from app.db.models.gate_type import GateType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase
from app.db.models.user import User
from app.services import release_readiness_service, release_gate_service


# ── Shared fixtures ──────────────────────────────────────────────────────────

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


async def _make_user(db_session: AsyncSession, tenant, *, username="foreignadmin") -> User:
    u = User(
        tenant_id=tenant.id,
        username=username,
        email=f"{username}@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _make_release(db_session: AsyncSession, tenant, user=None) -> Release:
    if user is None:
        user = await _make_user(db_session, tenant, username=f"raiser{tenant.id}")
    template = _release_lifecycle(tenant.id)
    db_session.add(template)
    await db_session.flush()
    r = Release(
        tenant_id=tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


async def _make_gate_type(
    db_session: AsyncSession, tenant, *, name="Sign-off",
    failure_behaviour="warn", is_active=True,
) -> GateType:
    gt = GateType(
        tenant_id=tenant.id, name=name, failure_behaviour=failure_behaviour,
        expected_evidence=[], is_active=is_active,
    )
    db_session.add(gt)
    await db_session.commit()
    await db_session.refresh(gt)
    return gt


async def _make_test_phase(db_session: AsyncSession, tenant, release) -> TestPhase:
    tp = TestPhase(tenant_id=tenant.id, release_id=release.id, name="SIT", order=0)
    db_session.add(tp)
    await db_session.commit()
    await db_session.refresh(tp)
    return tp


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    return await _make_release(db_session, test_tenant, test_user)


# ── Create/read round trip, over HTTP ────────────────────────────────────────

@pytest.mark.asyncio
async def test_creating_a_gate_with_a_type_stores_it_and_reads_back_over_http(
    client: AsyncClient, auth_headers, db_session, test_tenant, release,
):
    gate_type = await _make_gate_type(db_session, test_tenant, name="UAT Sign-off")

    due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    resp = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "UAT Gate", "due_date": due, "gate_type_id": gate_type.id},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["gate_type_id"] == gate_type.id
    gate_id = resp.json()["id"]

    listed = await client.get(f"/api/v1/releases/{release.id}/gates", headers=auth_headers)
    assert listed.status_code == 200
    row = next(g for g in listed.json() if g["id"] == gate_id)
    assert row["gate_type_id"] == gate_type.id
    assert row["test_phase_id"] is None


# ── Cross-tenant FK validation (service level — see conftest's `tenant` note:
# combining `tenant` with `auth_headers` mixes two tenants under one login and
# can pass vacuously; service-level calls with an explicit tenant_id avoid
# that trap entirely). ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_cross_tenant_gate_type_id_is_404_on_create(
    db_session, test_tenant, tenant, release,
):
    foreign_type = await _make_gate_type(db_session, tenant, name="Theirs")
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.create_gate(
            db_session, release.id,
            ReleaseGateCreate(
                name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
                gate_type_id=foreign_type.id,
            ),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_cross_tenant_gate_type_id_is_404_on_update(
    db_session, test_tenant, tenant, release,
):
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7)),
        test_tenant.id,
    )
    foreign_type = await _make_gate_type(db_session, tenant, name="Theirs")
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.update_gate(
            db_session, gate.id,
            ReleaseGateUpdate(gate_type_id=foreign_type.id),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_cross_tenant_test_phase_id_is_404_on_create(
    db_session, test_tenant, tenant, release,
):
    foreign_release = await _make_release(db_session, tenant)
    foreign_phase = await _make_test_phase(db_session, tenant, foreign_release)
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.create_gate(
            db_session, release.id,
            ReleaseGateCreate(
                name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
                test_phase_id=foreign_phase.id,
            ),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_cross_tenant_test_phase_id_is_404_on_update(
    db_session, test_tenant, tenant, release,
):
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7)),
        test_tenant.id,
    )
    foreign_release = await _make_release(db_session, tenant)
    foreign_phase = await _make_test_phase(db_session, tenant, foreign_release)
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.update_gate(
            db_session, gate.id,
            ReleaseGateUpdate(test_phase_id=foreign_phase.id),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


# ── In-tenant create coverage for test_phase_id (the "at least create" half
# the brief asks for, beyond the cross-tenant 404 above). ───────────────────

@pytest.mark.asyncio
async def test_creating_a_gate_with_a_test_phase_id_stores_it(
    db_session, test_tenant, release,
):
    phase = await _make_test_phase(db_session, test_tenant, release)
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(
            name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
            test_phase_id=phase.id,
        ),
        test_tenant.id,
    )
    assert gate.test_phase_id == phase.id


# ── exclude_unset semantics: omitted leaves alone, explicit null clears ────

@pytest.mark.asyncio
async def test_update_omitting_gate_type_id_leaves_it_unchanged(
    db_session, test_tenant, release,
):
    gate_type = await _make_gate_type(db_session, test_tenant)
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(
            name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
            gate_type_id=gate_type.id,
        ),
        test_tenant.id,
    )
    updated = await release_gate_service.update_gate(
        db_session, gate.id,
        ReleaseGateUpdate(name="G renamed"),  # gate_type_id omitted entirely
        test_tenant.id,
    )
    assert updated.name == "G renamed"
    assert updated.gate_type_id == gate_type.id


@pytest.mark.asyncio
async def test_update_with_explicit_null_clears_gate_type_id(
    db_session, test_tenant, release,
):
    gate_type = await _make_gate_type(db_session, test_tenant)
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(
            name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
            gate_type_id=gate_type.id,
        ),
        test_tenant.id,
    )
    updated = await release_gate_service.update_gate(
        db_session, gate.id,
        ReleaseGateUpdate(gate_type_id=None),
        test_tenant.id,
    )
    assert updated.gate_type_id is None


# ── The archived-value carve-out ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_form_update_resending_an_archived_type_unchanged_succeeds(
    db_session, test_tenant, release,
):
    """A gate typed while the type was live must stay editable after the type
    is archived — the UI's full-form PATCH always re-sends the existing
    gate_type_id, and that must not 404 an unrelated field's save."""
    from app.services import gate_type_service

    gate_type = await _make_gate_type(db_session, test_tenant, name="Legacy Sign-off")
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(
            name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
            gate_type_id=gate_type.id,
        ),
        test_tenant.id,
    )

    await gate_type_service.delete_type(db_session, gate_type.id, test_tenant.id)

    # Full-form save re-sending the (now archived) existing value, plus an
    # unrelated field change.
    updated = await release_gate_service.update_gate(
        db_session, gate.id,
        ReleaseGateUpdate(name="G renamed", gate_type_id=gate_type.id),
        test_tenant.id,
    )
    assert updated.name == "G renamed"
    assert updated.gate_type_id == gate_type.id


@pytest.mark.asyncio
async def test_assigning_an_archived_type_to_a_different_gate_is_refused(
    db_session, test_tenant, release,
):
    from app.services import gate_type_service

    gate_type = await _make_gate_type(db_session, test_tenant, name="Legacy Sign-off 2")
    await gate_type_service.delete_type(db_session, gate_type.id, test_tenant.id)

    other_gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="Other Gate", due_date=datetime.now(timezone.utc) + timedelta(days=7)),
        test_tenant.id,
    )
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.update_gate(
            db_session, other_gate.id,
            ReleaseGateUpdate(gate_type_id=gate_type.id),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_full_form_update_resending_an_unreachable_test_phase_id_unchanged_succeeds(
    db_session, test_tenant, release,
):
    """The test_phase_id counterpart of the gate_type_id carve-out above —
    deferred as a minor until I5 (C2 final review) gave the column a
    consumer, and now covered the same way gate_type_id already was.

    TestPhase has no delete service (nothing in the product retires one),
    so "otherwise unreachable" is produced directly, the same way this
    module already constructs cross-tenant rows for its FK probes: soft-
    delete the phase in place. A full-form save re-sending the gate's own
    (now-unreachable) test_phase_id, plus an unrelated field change, must
    still succeed — exactly as a full-form save re-sending an archived
    gate_type_id does.
    """
    phase = await _make_test_phase(db_session, test_tenant, release)
    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(
            name="G", due_date=datetime.now(timezone.utc) + timedelta(days=7),
            test_phase_id=phase.id,
        ),
        test_tenant.id,
    )

    phase.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    updated = await release_gate_service.update_gate(
        db_session, gate.id,
        ReleaseGateUpdate(name="G renamed", test_phase_id=phase.id),
        test_tenant.id,
    )
    assert updated.name == "G renamed"
    assert updated.test_phase_id == phase.id


@pytest.mark.asyncio
async def test_assigning_an_unreachable_test_phase_id_to_a_different_gate_is_refused(
    db_session, test_tenant, release,
):
    phase = await _make_test_phase(db_session, test_tenant, release)
    phase.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    other_gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="Other Gate", due_date=datetime.now(timezone.utc) + timedelta(days=7)),
        test_tenant.id,
    )
    with pytest.raises(HTTPException) as exc:
        await release_gate_service.update_gate(
            db_session, other_gate.id,
            ReleaseGateUpdate(test_phase_id=phase.id),
            test_tenant.id,
        )
    assert exc.value.status_code == 404


# ── The end-to-end proof: typing a gate makes it REACHABLE by the evaluator ─

@pytest.mark.asyncio
async def test_typing_a_gate_block_turns_gate_untyped_into_a_blocker(
    db_session, test_tenant, release,
):
    """Before this task: every gate is untyped forever, so evaluate() can only
    ever emit gate_untyped warnings and the block/warn/accept_with_exception
    behaviour C2 exists to deliver is dead code. This is the proof it is now
    reachable: assigning a block-behaviour type to a pending gate turns its
    gate_untyped warning into a real blocker."""
    block_type = await _make_gate_type(db_session, test_tenant, name="Go/No-Go", failure_behaviour="block")

    untyped_gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="Untyped Gate", due_date=datetime.now(timezone.utc) + timedelta(days=7)),
        test_tenant.id,
    )
    before = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert any(w.type == "gate_untyped" and w.ref_id == untyped_gate.id for w in before.warnings)
    assert not any(b.ref_id == untyped_gate.id for b in before.blockers)

    typed_gate = await release_gate_service.update_gate(
        db_session, untyped_gate.id,
        ReleaseGateUpdate(gate_type_id=block_type.id),
        test_tenant.id,
    )
    assert typed_gate.gate_type_id == block_type.id

    after = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert not any(w.type == "gate_untyped" and w.ref_id == untyped_gate.id for w in after.warnings)
    assert any(
        b.type == "gate_pending" and b.ref_id == untyped_gate.id and b.gate_type == "Go/No-Go"
        for b in after.blockers
    )
    assert after.ok is False
