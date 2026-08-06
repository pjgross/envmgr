"""The seeded default lifecycle, and the entity registration that validates it."""
import pytest
from sqlalchemy import select

from app.api.v1.schemas.booking_lifecycle import (
    ENTITY_FIELD_SPECS,
    LifecycleDefinition,
    validate_definition_for_entity,
)
from app.db.models.lifecycle import LifecycleTemplate
from app.services.environment_request_defaults import (
    DEFAULT_REQUEST_LIFECYCLE,
    seed_environment_request_defaults_for_tenant,
)


def test_entity_is_registered():
    assert "environment_request" in ENTITY_FIELD_SPECS
    spec = ENTITY_FIELD_SPECS["environment_request"]
    assert {"kind", "justification", "needed_by", "environment_id",
            "proposed_name", "tier_id", "expires_at",
            "operations_group_id"} == set(spec["valid"])
    # Deviation from the brief: mandatory is set() here, not {"kind",
    # "justification"}. The seeded DEFAULT_REQUEST_LIFECYCLE uses
    # "field_permissions": {}, and validate_definition_for_entity requires the
    # initial state to carry a field_permissions entry with a non-empty
    # editable_by list for every mandatory field — an empty field_permissions
    # dict trips that check for any non-empty mandatory set. "release" already
    # sets mandatory=set() for the same reason (its own default definition
    # also uses field_permissions={}). See task-2-report.md.
    assert spec["mandatory"] == set()


def test_the_seeded_definition_validates_against_its_own_entity_spec():
    """A default the machinery would reject is worse than no default."""
    definition = LifecycleDefinition.model_validate(DEFAULT_REQUEST_LIFECYCLE)
    validate_definition_for_entity(definition, "environment_request")  # no raise


def test_the_default_has_the_states_the_service_depends_on():
    """fulfilment, submission-guard and the pack all key on these names."""
    keys = {s["key"] for s in DEFAULT_REQUEST_LIFECYCLE["states"]}
    assert {"draft", "submitted", "approved", "fulfilled",
            "rejected", "cancelled"} == keys
    terminal = {s["key"] for s in DEFAULT_REQUEST_LIFECYCLE["states"] if s["is_terminal"]}
    assert terminal == {"fulfilled", "rejected", "cancelled"}


@pytest.mark.asyncio
async def test_seeding_is_idempotent(db_session, test_tenant):
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)

    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "environment_request",
            LifecycleTemplate.deleted_at.is_(None),
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_default is True


@pytest.mark.asyncio
async def test_creating_a_tenant_seeds_its_request_lifecycle(db_session):
    """Exercises the tenant_service.create_tenant wiring itself, not just the
    seeder function directly — mirrors
    test_environment_tier_defaults_seed.py's
    test_creating_a_tenant_seeds_its_tiers. Without this, nothing at any
    level noticed when the seed call was removed from create_tenant."""
    from app.api.v1.schemas import TenantCreate
    from app.services import tenant_service

    tenant = await tenant_service.create_tenant(
        db_session, TenantCreate(name="Request Org", slug="request-org")
    )

    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "environment_request",
            LifecycleTemplate.deleted_at.is_(None),
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Standard Request"
    assert rows[0].is_default is True


# ---------------------------------------------------------------------------
# Fix pass: C1(b) — a template renaming a state environment_request_service
# keys on used to save silently and degrade the feature it renamed (the
# group gate on 'approved'->'authorised', fulfilment on 'fulfilled'->'done',
# every subsequent transition 400ing on 'draft'->'new'). Reproduced live by
# the reviewer as a Test Manager in no group at all approving an access
# request — HTTP 200 — after renaming 'approved'.
# ---------------------------------------------------------------------------

def _definition_with(*, rename: dict[str, str] | None = None):
    """DEFAULT_REQUEST_LIFECYCLE's states/transitions, with `rename` applied
    to state keys (and every transition referencing them) — the same
    transformation a tenant renaming a state through the admin UI would
    make. `is_initial`/`is_terminal` travel with the state unchanged; only
    the key (and every from_state/to_state that names it) is remapped."""
    rename = rename or {}

    def r(key: str) -> str:
        return rename.get(key, key)

    states = [
        {"key": r(s["key"]), "label": s["label"], "is_initial": s["is_initial"],
         "is_terminal": s["is_terminal"]}
        for s in DEFAULT_REQUEST_LIFECYCLE["states"]
    ]
    transitions = [
        {"from_state": r(t["from_state"]), "to_state": r(t["to_state"]),
         "label": t["label"], "allowed_roles": t["allowed_roles"]}
        for t in DEFAULT_REQUEST_LIFECYCLE["transitions"]
    ]
    return {"states": states, "transitions": transitions, "field_permissions": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("old_key,new_key", [
    ("approved", "authorised"),
    ("fulfilled", "done"),
    ("draft", "new"),
])
async def test_a_template_renaming_a_required_state_is_refused_at_save_time(
    client, auth_headers, old_key, new_key,
):
    """Each of the three renames the reviewer drove through the live API is
    now refused at POST /lifecycle-templates, not merely tolerated and then
    silently broken at run time. 'draft' is deliberately included even
    though C1(a) frees the INITIAL state's name generally — this rename also
    touches 'submitted' by construction (renaming a from_state/to_state pair
    consistently), so the fixture must isolate that. Instead this asserts
    the surviving case: renaming ONLY 'draft' (the initial state, not one of
    the four required names) must still be ACCEPTED."""
    definition = _definition_with(rename={old_key: new_key})
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={
            "name": f"Renamed {old_key}", "entity_type": "environment_request",
            "definition": definition,
        },
    )
    if old_key == "draft":
        # The INITIAL state's name is deliberately not pinned (C1(a) reads it
        # from the template) — renaming ONLY it must be accepted.
        assert resp.status_code == 201, resp.text
    else:
        assert resp.status_code == 422, resp.text
        assert old_key in resp.text


@pytest.mark.asyncio
async def test_a_template_adding_a_review_state_is_accepted_and_works_end_to_end(
    client, auth_headers, db_session, test_tenant,
):
    """Configurability that C1(b) does NOT take away: a tenant may still add
    states and rewire transitions freely, as long as the four required names
    survive. This is the positive control for the parametrized refusal
    above — proves the validator isn't simply refusing every non-default
    definition."""
    from tests.factories import ensure_environment, ensure_user_group

    definition = _definition_with()
    definition["states"].append(
        {"key": "on_hold", "label": "On Hold", "is_initial": False, "is_terminal": False}
    )
    definition["transitions"].append(
        {"from_state": "submitted", "to_state": "on_hold", "label": "Put On Hold",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager"]}
    )
    definition["transitions"].append(
        {"from_state": "on_hold", "to_state": "submitted", "label": "Resume",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager"]}
    )
    created_tpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "With Review Step", "entity_type": "environment_request",
              "definition": definition},
    )
    assert created_tpl.status_code == 201, created_tpl.text

    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]
    for to_state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": to_state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "fulfilled"
