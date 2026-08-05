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
