from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.v1.schemas.gate_evidence import GateEvidenceCreate
from app.db.models.gate_evidence import GateEvidence
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_evidence_service
from tests.factories import ensure_deployment, ensure_environment


@pytest_asyncio.fixture
async def gate(db_session, test_tenant, test_user) -> ReleaseGate:
    """A persisted ReleaseGate under a fresh Release in test_tenant."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Test Major",
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
    db_session.add(template)
    await db_session.flush()

    release = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    g = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="SIT Exit",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)
    return g


@pytest_asyncio.fixture
async def other_tenant_deployment(db_session, second_tenant_factory):
    """A deployment that belongs to a tenant other than test_tenant."""
    other_tenant, _other_admin = await second_tenant_factory()
    other_env = await ensure_environment(db_session, other_tenant.id)
    deployment = await ensure_deployment(
        db_session, other_tenant.id, other_env.id,
        deployed_at=datetime.now(timezone.utc),
    )
    await db_session.commit()
    await db_session.refresh(deployment)
    return deployment


@pytest.mark.asyncio
async def test_a_deployment_from_another_tenant_is_refused(
    db_session, test_tenant, test_user, gate, other_tenant_deployment
):
    with pytest.raises(HTTPException) as exc:
        await gate_evidence_service.add_evidence(
            db_session, gate.id, test_tenant.id, test_user.id,
            GateEvidenceCreate(
                kind="Test execution report", label="Regression run",
                url="https://ci.example/1", deployment_id=other_tenant_deployment.id,
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_needs_no_deployment(db_session, test_tenant, test_user, gate):
    """A licence report or a runbook vouches for no particular deployment.
    requires_deployment_link is advisory — it shapes the verdict, it does not
    refuse the write."""
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Ops runbook", url="https://wiki/rb"),
    )
    assert row.deployment_id is None


@pytest.mark.asyncio
async def test_an_unlisted_kind_is_accepted(db_session, test_tenant, test_user, gate):
    """kind is free text. The UI offers the type's expected kinds; an unlisted
    one is accepted and simply satisfies no expectation."""
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Something bespoke", label="One-off", url=None),
    )
    assert row.kind == "Something bespoke"


@pytest.mark.asyncio
async def test_a_deployment_in_the_same_tenant_is_accepted_even_off_the_gates_release(
    db_session, test_tenant, test_user, gate
):
    """The deployment need not belong to the gate's own release — a QA
    sign-off may cite an earlier release's deployment into the same
    environment."""
    env = await ensure_environment(db_session, test_tenant.id)
    deployment = await ensure_deployment(
        db_session, test_tenant.id, env.id, deployed_at=datetime.now(timezone.utc)
    )
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(
            kind="Deployment record", label="Prior deploy",
            url=None, deployment_id=deployment.id,
        ),
    )
    assert row.deployment_id == deployment.id


@pytest.mark.asyncio
async def test_list_evidence_excludes_soft_deleted_rows(
    db_session, test_tenant, test_user, gate
):
    kept = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Kept", url=None),
    )
    removed = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Removed", url=None),
    )
    await gate_evidence_service.delete_evidence(db_session, removed.id, test_tenant.id)

    rows = await gate_evidence_service.list_evidence(db_session, gate.id, test_tenant.id)
    labels = [r.label for r in rows]
    assert "Kept" in labels
    assert "Removed" not in labels
    assert kept.id in [r.id for r in rows]


@pytest.mark.asyncio
async def test_deleting_evidence_from_another_tenant_is_refused(
    db_session, test_tenant, test_user, gate, second_tenant_factory
):
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Mine", url=None),
    )
    other_tenant, _ = await second_tenant_factory()

    with pytest.raises(HTTPException) as exc:
        await gate_evidence_service.delete_evidence(db_session, row.id, other_tenant.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_for_gates_is_one_query_batched_by_gate(
    db_session, test_tenant, test_user, gate
):
    """A dict keyed by every requested gate id, including gates with none —
    not just the ones that have rows."""
    await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Only one", url=None),
    )
    other_gate_id = gate.id + 999  # no rows for this id

    grouped = await gate_evidence_service.evidence_for_gates(
        db_session, test_tenant.id, [gate.id, other_gate_id]
    )
    assert len(grouped[gate.id]) == 1
    assert grouped[other_gate_id] == []


@pytest.mark.asyncio
async def test_evidence_for_gates_does_not_leak_another_tenants_evidence(
    db_session, test_tenant, test_user, gate, second_tenant_factory
):
    """evidence_for_gates' tenant filter is its ONLY isolation guard — unlike
    list_evidence/add_evidence/delete_evidence, there is no get_gate
    precursor to 404 a cross-tenant caller first. Proven by mutation: this
    test fails if `GateEvidence.tenant_id == tenant_id` is removed from the
    query, because gate_id.in_(gate_ids) alone would still match tenant B's
    row."""
    await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Tenant A's evidence", url=None),
    )

    other_tenant, other_admin = await second_tenant_factory()
    other_template = LifecycleTemplate(
        tenant_id=other_tenant.id,
        entity_type="release",
        name="Other Major",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(other_template)
    await db_session.flush()
    other_release = Release(
        tenant_id=other_tenant.id,
        name="Other R",
        release_type="Major",
        lifecycle_template_id=other_template.id,
        raised_by=other_admin.id,
    )
    db_session.add(other_release)
    await db_session.flush()
    other_gate = ReleaseGate(
        tenant_id=other_tenant.id,
        release_id=other_release.id,
        name="Other Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(other_gate)
    await db_session.flush()

    await gate_evidence_service.add_evidence(
        db_session, other_gate.id, other_tenant.id, other_admin.id,
        GateEvidenceCreate(kind="Runbook", label="Tenant B's evidence", url=None),
    )

    grouped = await gate_evidence_service.evidence_for_gates(
        db_session, test_tenant.id, [gate.id, other_gate.id]
    )
    assert [row.label for row in grouped[gate.id]] == ["Tenant A's evidence"]
    assert grouped[other_gate.id] == []


@pytest.mark.asyncio
async def test_list_evidence_does_not_return_a_row_with_a_mismatched_tenant_id(
    db_session, test_tenant, test_user, gate, second_tenant_factory
):
    """list_evidence's own tenant filter, isolated from get_gate's 404. A
    legitimate write can never produce a GateEvidence row whose tenant_id
    disagrees with its gate's tenant (add_evidence's get_gate call sees to
    that) — so this inserts the row directly, simulating corrupted data or a
    second write path that skips validation, to exercise the query's filter
    on its own. Proven by mutation: fails if
    `GateEvidence.tenant_id == tenant_id` is removed from list_evidence's
    query, since gate_id == gate.id alone would still match this row."""
    other_tenant, _other_admin = await second_tenant_factory()

    mismatched = GateEvidence(
        tenant_id=other_tenant.id,  # deliberately NOT test_tenant.id
        gate_id=gate.id,  # but points at test_tenant's own gate
        kind="Runbook",
        label="Should never be returned",
        added_by=test_user.id,
    )
    db_session.add(mismatched)
    await db_session.flush()

    rows = await gate_evidence_service.list_evidence(db_session, gate.id, test_tenant.id)
    assert [r.label for r in rows] == []
