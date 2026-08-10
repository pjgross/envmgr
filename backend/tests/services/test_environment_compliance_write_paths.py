"""The stored verdict's integrity.

A verdict that nothing recomputes is worse than no verdict, so this drives an
environment through EVERY write path and asserts the stored value equals a
freshly computed one each time.

WHERE THE REFUSAL LIVES, AND WHERE IT DELIBERATELY DOES NOT
-----------------------------------------------------------
Four paths can set `environment.name`, and they do NOT get the same treatment:

* `create_environment` (the API wrapper) and `update_environment` REFUSE a
  non-conforming name, because the person typing it can fix it there and then.
* `create_environment_record` — the shared minting function — only RECORDS the
  verdict. The spreadsheet import calls it directly, per row, inside an
  `except (ValueError, ValidationError)`; an `HTTPException` raised from here
  escapes that handler and kills the ENTIRE upload, which is a failure this
  codebase has already shipped once (see CLAUDE.md). One non-conforming row
  must not throw away every other row in the file.
* Request FULFILMENT records and never refuses: an approved request that cannot
  be fulfilled is an unrecoverable state, the exact class B3b produced twice.
  The pattern is checked at SUBMIT time instead, while the name is correctable.

The plan put the refusal in `create_environment_record` itself, which would
have given the import the abort-the-upload behaviour. That is the one deviation
from Task 5 as written, and `test_a_spreadsheet_import_is_never_refused_by_the
_naming_rule` is its guard.
"""
import io

import openpyxl
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services import environment_compliance_service as svc
from app.services import environment_request_service, excel_import_service
from app.services.environment_tier_defaults import (
    seed_environment_tier_defaults_for_tenant,
)
from tests.factories import (
    ensure_environment_request,
    ensure_environment_tier,
    post_environment,
)

POLICY_URL = "/api/v1/tenant/environment-naming-policy"
PATTERN = r"[a-z]+-(dev|uat|prod)-\d{2}"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=PATTERN,
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    b.update(kw)
    return b


async def _assert_verdict_is_honest(db_session, tenant_id):
    """Every stored verdict equals what the evaluator says right now."""
    policy = await svc.load_policy(db_session, tenant_id)
    envs = (
        (
            await db_session.execute(
                select(Environment).where(
                    Environment.tenant_id == tenant_id,
                    Environment.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert envs, "nothing was asserted — the tenant has no environments"
    for env in envs:
        assert env.name_compliant == svc.evaluate_name(policy, env.name), (
            f"stored verdict for '{env.name}' is stale"
        )


@pytest.mark.asyncio
async def test_create_evaluates_the_new_name(
    client, auth_headers, db_session, test_tenant
):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    r = await post_environment(client, auth_headers, "payments-uat-01")
    assert r.status_code == 201, r.text
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_a_rename_re_evaluates(client, auth_headers, db_session, test_tenant):
    """The rename must CHANGE the verdict, or this test cannot see the
    re-evaluation at all.

    Renaming one conforming name to another leaves the stored True equal to a
    freshly computed True, so dropping the re-evaluation entirely keeps the
    whole file green — measured, not theorised. Non-conforming to conforming is
    the only direction that is both observable and permitted: the reverse is
    refused outright by `assert_name_allowed`.
    """
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    stored = await db_session.get(Environment, env_id)
    await db_session.refresh(stored)
    assert stored.name_compliant is False, "the policy save should have judged it"

    patched = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "payments-uat-01"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    await db_session.refresh(stored)
    assert stored.name_compliant is True, "the rename did not re-evaluate"
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_a_full_form_save_with_an_unchanged_bad_name_is_accepted(
    client, auth_headers, db_session, test_tenant
):
    """Activating a policy must not freeze the estate."""
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    saved = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "Legacy Box", "description": "still here"},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_changing_a_bad_name_to_another_bad_name_is_refused(client, auth_headers):
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    refused = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "Legacy Box 2"},
        headers=auth_headers,
    )
    assert refused.status_code == 422
    # The example travels in the message, so the refusal teaches a name that works.
    assert "payments-uat-01" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_creating_a_non_conforming_environment_is_refused(client, auth_headers):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    r = await post_environment(client, auth_headers, "Nope")
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_a_policy_change_re_evaluates_everything(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "billing-dev-07")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    await client.put(
        POLICY_URL,
        json=_body(name_pattern=r"payments-.*", name_pattern_example="payments-x"),
        headers=auth_headers,
    )
    await _assert_verdict_is_honest(db_session, test_tenant.id)


# ---------------------------------------------------------------------------
# The two paths that RECORD and never refuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fulfilling_an_approved_request_never_422s_on_the_naming_rule(
    client,
    auth_headers,
    db_session,
    test_tenant,
    test_user,
    environment_request_lifecycle,
):
    """An approved request that cannot be fulfilled is an unrecoverable state —
    B3b produced that shape twice. Fulfilment records the verdict; it never
    refuses. The check belongs at submit time, while the name is correctable.

    Driven through the real `transition`, not `_fulfil_new_environment`, so the
    assertion covers the path an approver actually takes.
    """
    from tests.factories import ensure_user_group

    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id)
    req = await ensure_environment_request(
        db_session,
        test_tenant.id,
        kind="new_environment",
        status="approved",
        environment_id=None,
        proposed_name="Not Conforming At All",
        tier_id=tier.id,
        # Fulfilment refuses a request with no operating team — B3a's rule, and
        # nothing to do with B2. Supplied so the naming rule is what this test
        # is actually exercising.
        operations_group_id=group.id,
    )
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    view = await environment_request_service.transition(
        db_session, req.id, "fulfilled", test_user, test_tenant.id
    )
    assert view.request.status == "fulfilled"

    env = (
        await db_session.execute(
            select(Environment).where(
                Environment.tenant_id == test_tenant.id,
                Environment.name == "Not Conforming At All",
            )
        )
    ).scalar_one()
    assert env.name_compliant is False


@pytest.mark.asyncio
async def test_a_spreadsheet_import_is_never_refused_by_the_naming_rule(
    client, auth_headers, db_session, test_tenant, test_user
):
    """One non-conforming row must not throw away the rest of the file.

    The import calls `create_environment_record` per row inside an
    `except (ValueError, ValidationError)`. An HTTPException raised from there
    escapes that handler and aborts the whole upload — a failure this codebase
    has already shipped once. So the record path records and does not refuse,
    and the verdict is still stored honestly for every row.
    """
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Type", "Description"])
    ws.append(["Legacy Box", "SIT", "does not conform"])
    ws.append(["payments-uat-01", "SIT", "conforms"])
    buf = io.BytesIO()
    wb.save(buf)

    result = await excel_import_service.import_environments(
        db_session, buf.getvalue(), test_tenant.id, test_user.id
    )
    assert result["created"] == 2, result

    await _assert_verdict_is_honest(db_session, test_tenant.id)


# ---------------------------------------------------------------------------
# Submit time: where the request's name IS refused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submitting_a_request_naming_a_non_conforming_environment_is_refused(
    client,
    auth_headers,
    db_session,
    test_tenant,
    test_user,
    environment_request_lifecycle,
):
    """Caught here, the requester can still edit the name. Caught at fulfilment
    it would be too late, and not caught at all it would mint a permanently
    non-compliant environment through a path with no refusal in it."""
    from fastapi import HTTPException

    tier = await ensure_environment_tier(db_session, test_tenant.id)
    req = await ensure_environment_request(
        db_session,
        test_tenant.id,
        kind="new_environment",
        status="draft",
        environment_id=None,
        proposed_name="Not Conforming At All",
        tier_id=tier.id,
    )
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    with pytest.raises(HTTPException) as exc:
        await environment_request_service.transition(
            db_session, req.id, "submitted", test_user, test_tenant.id
        )
    assert exc.value.status_code == 422
    assert "payments-uat-01" in exc.value.detail


@pytest.mark.asyncio
async def test_submitting_an_access_request_is_unaffected_by_the_naming_rule(
    client,
    auth_headers,
    db_session,
    test_tenant,
    test_user,
    environment_request_lifecycle,
):
    """An access request has no proposed_name to judge. Judging the target
    environment's existing name instead would block access to exactly the
    legacy environments people most need access to."""
    from tests.factories import ensure_environment, ensure_user_group

    env = await ensure_environment(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id)
    env.name = "Legacy Box"
    env.operations_group_id = group.id
    await db_session.flush()

    req = await ensure_environment_request(
        db_session, test_tenant.id, status="draft", environment_id=env.id
    )
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    view = await environment_request_service.transition(
        db_session, req.id, "submitted", test_user, test_tenant.id
    )
    assert view.request.status == "submitted"
