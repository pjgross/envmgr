"""THE guard on B2's design, descended from A1's
`test_an_agreement_changes_no_booking_behaviour` and A4's
`test_a_contention_changes_no_booking_behaviour`.

If this fails, B2 has started acting.

B2's ONE refusal is a 422 on a CHANGED environment name that fails the pattern
(plus the same check on a request's proposed name, at submit). Everything else
— the gap, the quarantine, the messages — is a label and a filter. No booking
is refused, transitioned or gated, and no environment is made unusable by
failing its tenant's convention.

Proved non-vacuous rather than assumed: inserting a real refusal into
`booking_service.create_request` (raise on `name_compliant is False`) makes
`test_a_quarantined_environment_can_still_be_booked` fail, and reverting it
makes it pass again.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services import environment_compliance_service as svc
from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"
ENVS_URL = "/api/v1/environments/"


async def _quarantine(client, headers, db_session, tenant_id, name):
    """Create `name`, put a policy over it that it fails, and run both grace
    clocks out so it is genuinely quarantined.

    Both clocks: the policy's `effective_from` AND the environment's own
    `created_at`. Ageing one alone leaves it un-quarantined and every assertion
    below would then pass for the wrong reason.
    """
    created = await post_environment(client, headers, name)
    assert created.status_code == 201, created.text
    env_id = created.json()["id"]
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": r"[a-z]+-\d{2}",
            "name_pattern_example": "payments-01",
            "required_attributes": [],
            "grace_days": 0,
        },
        headers=headers,
    )
    then = datetime.now(timezone.utc) - timedelta(days=30)
    env = (
        await db_session.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id, Environment.name == name
            )
        )
    ).scalar_one()
    env.created_at = then
    policy = await svc.load_policy(db_session, tenant_id)
    policy.effective_from = then
    await db_session.flush()

    listed = (
        await client.get(ENVS_URL, params={"quarantined": "true"}, headers=headers)
    ).json()
    assert [e["name"] for e in listed] == [name], "precondition: it is quarantined"
    return env_id


@pytest.mark.asyncio
async def test_a_quarantined_environment_can_still_be_booked(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    env_id = await _quarantine(
        client, auth_headers, db_session, test_tenant.id, "Legacy Box"
    )

    booking = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "B2 must not block this",
            "booking_type_id": test_booking_type.id,
            "start_date": "2026-05-01T00:00:00Z",
            "end_date": "2026-05-03T00:00:00Z",
            "environment_ids": [env_id],
            "context_tag": "none",
        },
        headers=auth_headers,
    )
    assert booking.status_code == 201, booking.text
    assert booking.json()["request"]["bookings"][0]["environment_id"] == env_id


@pytest.mark.asyncio
async def test_a_quarantined_environments_booking_can_still_transition(
    client, auth_headers, db_session, test_tenant
):
    """The other half of "never gated": B2 must not narrow what a booking on a
    quarantined environment may do next. A4's guard checks the same shape for
    contention.

    NOT the `test_booking_type` fixture, deliberately. Its lifecycle template
    declares `"transitions": []`, so `allowed-transitions` returns an empty list
    for every booking whatever the rules say — this test passed against it while
    asserting nothing, which is precisely how A3's reviewer gated
    `TransitionButtons` on the gap and watched all 50 page tests stay green. The
    booking type here has a real draft→submitted transition, so an empty list
    means gating and nothing else.
    """
    template = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={
            "name": "B2 guard",
            "definition": {
                "states": [
                    {
                        "key": "draft",
                        "label": "Draft",
                        "is_initial": True,
                        "is_terminal": False,
                    },
                    {
                        "key": "submitted",
                        "label": "Submitted",
                        "is_initial": False,
                        "is_terminal": False,
                    },
                ],
                "transitions": [
                    {
                        "from_state": "draft",
                        "to_state": "submitted",
                        "label": "Submit",
                        "allowed_roles": ["Admin"],
                    }
                ],
                # Required by the template validator: the initial state must
                # give every mandatory field at least one editable role.
                "field_permissions": {
                    "draft": {
                        "standard_fields": {
                            field: {"editable_by": ["Admin"]}
                            for field in (
                                "project_name",
                                "start_date",
                                "end_date",
                                "booking_type",
                            )
                        }
                    }
                },
            },
        },
    )
    assert template.status_code == 201, template.text
    booking_type = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "B2 guard booking",
            "lifecycle_template_id": template.json()["id"],
        },
    )
    assert booking_type.status_code == 201, booking_type.text

    env_id = await _quarantine(
        client, auth_headers, db_session, test_tenant.id, "Legacy Box"
    )
    created = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "B2 must not gate this",
            "booking_type_id": booking_type.json()["id"],
            "start_date": "2026-05-01T00:00:00Z",
            "end_date": "2026-05-03T00:00:00Z",
            "environment_ids": [env_id],
            "context_tag": "none",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    allowed = await client.get(
        f"/api/v1/bookings/{booking_id}/allowed-transitions", headers=auth_headers
    )
    assert allowed.status_code == 200, allowed.text
    assert [t["to_state"] for t in allowed.json()] == ["submitted"], (
        "a quarantined environment's booking was offered no transitions at all"
    )


@pytest.mark.asyncio
async def test_a_quarantined_environment_is_still_editable_and_still_active(
    client, auth_headers, db_session, test_tenant
):
    """Quarantine is a LABEL. It does not deactivate the environment, and it
    does not freeze the row — a full-form save re-sending the failing name is
    still accepted, or activating a policy would strand every environment it
    flags."""
    env_id = await _quarantine(
        client, auth_headers, db_session, test_tenant.id, "Legacy Box"
    )

    detail = (await client.get(f"{ENVS_URL}{env_id}", headers=auth_headers)).json()
    assert detail["quarantined"] is True, "precondition"
    assert detail["status"] == "active", "quarantine must not deactivate anything"

    saved = await client.patch(
        f"{ENVS_URL}{env_id}",
        json={"name": "Legacy Box", "description": "still editable"},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["description"] == "still editable"
