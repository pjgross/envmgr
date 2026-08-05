"""The request table and the six handover columns B3b adds."""
import pytest
from sqlalchemy import select

from app.db.models.environment_request import EnvironmentRequest
from tests.factories import ensure_environment, ensure_environment_request


@pytest.mark.asyncio
async def test_access_request_persists(db_session, test_tenant):
    req = await ensure_environment_request(db_session, test_tenant.id)
    assert req.id is not None
    assert req.kind == "access"
    assert req.status == "draft"
    assert req.deleted_at is None
    assert req.created_environment_id is None


@pytest.mark.asyncio
async def test_new_environment_request_needs_no_environment(db_session, test_tenant):
    """kind='new_environment' has no target yet — environment_id stays null."""
    req = await ensure_environment_request(
        db_session, test_tenant.id, kind="new_environment",
        environment_id=None, proposed_name="Mortgage PERF",
    )
    assert req.environment_id is None
    assert req.proposed_name == "Mortgage PERF"


@pytest.mark.asyncio
async def test_handover_fields_default_to_null(db_session, test_tenant):
    """A newly created environment has nothing to hand over yet — that is
    correct, not a gap. The operating team fills these in after building it."""
    env = await ensure_environment(db_session, test_tenant.id)
    assert env.access_url is None
    assert env.connection_notes is None
    assert env.support_contact is None
    assert env.sla_notes is None
    assert env.known_limitations is None
    assert env.decommission_notes is None


@pytest.mark.asyncio
async def test_created_environment_link_survives_a_round_trip(db_session, test_tenant):
    """The audit link answering 'where did this environment come from?'."""
    env = await ensure_environment(db_session, test_tenant.id, slot=3)
    req = await ensure_environment_request(
        db_session, test_tenant.id, kind="new_environment",
        environment_id=None, proposed_name="Built",
    )
    req.created_environment_id = env.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(EnvironmentRequest.created_environment_id)
        .where(EnvironmentRequest.id == req.id)
    )).scalar_one()
    assert stored == env.id
