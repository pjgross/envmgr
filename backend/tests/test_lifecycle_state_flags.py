"""The five lifecycle state flags survive a save and obey their rules.

`is_failed` was silently dropped on every save before C6: it was read by the
DORA change-failure rate but never declared on `LifecycleState`, and both
create and update store `definition.model_dump()`. The first test here is the
regression test for that.
"""
import pytest


def _definition(states, transitions=None):
    keys = [s["key"] for s in states]
    return {
        "states": states,
        "transitions": transitions or [
            {"from_state": keys[0], "to_state": keys[-1], "label": "Go",
             "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {k: {"standard_fields": {}, "custom_fields": {}} for k in keys},
    }


DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}


async def _post(client, headers, states, applies_to_kind="project"):
    return await client.post(
        "/api/v1/tenant/lifecycle-templates", headers=headers,
        json={"name": "Flags", "entity_type": "release",
              "applies_to_kind": applies_to_kind, "definition": _definition(states)},
    )


@pytest.mark.asyncio
async def test_all_five_flags_survive_create_read_update_and_copy(client, auth_headers):
    done = {"key": "done", "label": "Done", "is_terminal": True, "is_failed": True,
            "marks_deployed": True, "is_closed": True,
            "requires_pir_complete": True, "requires_handover_confirmed": True}
    resp = await _post(client, auth_headers, [DRAFT, done])
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]

    def _done(body):
        return next(s for s in body["definition"]["states"] if s["key"] == "done")

    for flag in ("is_failed", "marks_deployed", "is_closed",
                 "requires_pir_complete", "requires_handover_confirmed"):
        assert _done(resp.json())[flag] is True, flag

    got = await client.get(f"/api/v1/tenant/lifecycle-templates/{tid}", headers=auth_headers)
    assert _done(got.json())["is_failed"] is True

    put = await client.put(f"/api/v1/tenant/lifecycle-templates/{tid}", headers=auth_headers,
                           json={"definition": _definition([DRAFT, done])})
    assert put.status_code == 200, put.text
    assert _done(put.json())["is_failed"] is True

    copy = await client.post(f"/api/v1/tenant/lifecycle-templates/{tid}/copy",
                             headers=auth_headers, json={"name": "Flags copy"})
    assert copy.status_code == 201, copy.text
    assert _done(copy.json())["requires_pir_complete"] is True


@pytest.mark.asyncio
async def test_is_closed_requires_is_terminal(client, auth_headers):
    bad = {"key": "mid", "label": "Mid", "is_terminal": False, "is_closed": True}
    resp = await _post(client, auth_headers, [DRAFT, bad])
    assert resp.status_code == 422, resp.text
    assert "mid" in resp.text and "is_closed" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["requires_pir_complete", "requires_handover_confirmed"])
async def test_requirements_need_is_closed(client, auth_headers, flag):
    bad = {"key": "done", "label": "Done", "is_terminal": True, flag: True}
    resp = await _post(client, auth_headers, [DRAFT, bad])
    assert resp.status_code == 422, resp.text
    assert "done" in resp.text and flag in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["marks_deployed", "is_closed",
                                  "requires_pir_complete", "requires_handover_confirmed"])
async def test_enterprise_templates_refuse_every_new_flag(client, auth_headers, flag):
    done = {"key": "done", "label": "Done", "is_terminal": True,
            "is_closed": True, "requires_pir_complete": flag == "requires_pir_complete",
            "requires_handover_confirmed": flag == "requires_handover_confirmed",
            "marks_deployed": flag == "marks_deployed"}
    resp = await _post(client, auth_headers, [DRAFT, done], applies_to_kind="enterprise")
    assert resp.status_code == 422, resp.text
    assert "enterprise" in resp.text.lower()


@pytest.mark.asyncio
async def test_a_state_with_no_new_flags_is_unchanged_on_a_project_template(client, auth_headers):
    done = {"key": "done", "label": "Done", "is_terminal": True}
    resp = await _post(client, auth_headers, [DRAFT, done])
    assert resp.status_code == 201, resp.text
    state = next(s for s in resp.json()["definition"]["states"] if s["key"] == "done")
    assert state["is_closed"] is False and state["marks_deployed"] is False
