"""`GET /deployments` must not 500 on an event_id that isn't a UUID.

The column is `String(36)` (`app/db/models/deployment.py`, and the original
migration), and `deployment_service` stores and compares `str(payload.event_id)`
— so at the storage boundary an event id is a string of up to 36 characters.
`DeploymentRead` declared it as a `UUID`, which is a stricter claim than the
column can guarantee.

The failure mode that matters is the blast radius, not the single row: the
response model is applied per row while serialising the whole page, so **one
row the schema rejects makes the entire list endpoint 500**. Every deployment
in the dev database carried a `dora-evt-N` event id, which made the Deployments
page permanently empty with a 500 behind it.

The webhook input schema still requires a UUID, so this does not loosen what
the supported ingest path accepts — it only stops the read side from asserting
something the column never enforced.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Response

from app.api.v1 import deployments as deployments_api
from app.core.pagination import Page, Sort
from app.db.models.deployment import Deployment
from tests.factories import ensure_build, ensure_change_request, ensure_environment


async def _deployment(db_session, tenant_id, event_id: str) -> Deployment:
    build = await ensure_build(db_session, tenant_id)
    env = await ensure_environment(db_session, tenant_id)
    cr = await ensure_change_request(db_session, tenant_id)
    row = Deployment(
        tenant_id=tenant_id,
        build_id=build.id,
        environment_id=env.id,
        change_request_id=cr.id,
        event_id=event_id,
        deployer_name="alice",
        status="success",
        deployed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _list(db_session, user):
    return await deployments_api.list_deployments(
        response=Response(),
        environment_id=None,
        release_id=None,
        build_id=None,
        status_filter=None,
        date_from=None,
        date_to=None,
        environment_search=None,
        release_search=None,
        page=Page(limit=25, offset=0),
        sort=Sort(column=Deployment.deployed_at, descending=True),
        db=db_session,
        current_user=user,
    )


@pytest.mark.asyncio
async def test_a_non_uuid_event_id_is_returned_rather_than_raising(
    db_session, test_tenant, test_user
):
    """The reported shape: every dev row used `dora-evt-N`."""
    test_user.active_tenant_id = test_user.tenant_id
    await _deployment(db_session, test_tenant.id, "dora-evt-3")

    rows = await _list(db_session, test_user)

    assert [r.event_id for r in rows] == ["dora-evt-3"]


@pytest.mark.asyncio
async def test_one_unparseable_row_does_not_take_out_the_whole_page(
    db_session, test_tenant, test_user
):
    """The blast radius is what made this severe. A single bad row used to fail
    the response model for the entire list, so a page of otherwise-valid
    deployments returned 500 rather than degrading to one odd-looking cell."""
    test_user.active_tenant_id = test_user.tenant_id
    good = str(uuid.uuid4())
    await _deployment(db_session, test_tenant.id, good)
    await _deployment(db_session, test_tenant.id, "dora-evt-3")

    rows = await _list(db_session, test_user)

    assert len(rows) == 2
    assert set(r.event_id for r in rows) == {good, "dora-evt-3"}


@pytest.mark.asyncio
async def test_a_uuid_event_id_still_round_trips_as_its_canonical_string(
    db_session, test_tenant, test_user
):
    """Loosening the type must not change what a well-formed id looks like on
    the wire — clients matching on it would break."""
    test_user.active_tenant_id = test_user.tenant_id
    event_id = str(uuid.uuid4())
    await _deployment(db_session, test_tenant.id, event_id)

    rows = await _list(db_session, test_user)

    assert rows[0].event_id == event_id
