"""C5a REFUSES ONLY WRITES TO ITS OWN RUNBOOK RECORDS.

A runbook — however incomplete, failed or out of order — changes nothing
anywhere else: the release's readiness verdict is byte-identical with and
without one, the release still transitions, and no module outside the runbook
router and /me/work so much as imports a runbook service.

Proved non-vacuous (record in the commit): adding
`from app.services import runbook_service` to release_readiness_service makes
test_nothing_outside_the_runbook_imports_it fail; and appending a blocker for
an unfinished runbook inside evaluate() makes
test_readiness_is_identical_with_and_without_a_runbook fail.

C5b WILL deliberately amend exactly one test here when it folds runbook
findings into readiness — the way C6 amended test_pir_records_never_refuses.

Ruling R2: there is no `GET /releases/{id}/allowed-transitions` route (the
runbook's own `allowed_transitions` on a task is a different concept from any
release-transition-vocabulary endpoint, which does not exist). The seeded
"Major" lifecycle template offers `draft -> submitted`, but `submitted` carries
`required_fields: ["name", "release_type", "target_date"]` and `make_release`
sets no `target_date`, so that transition 422s. `draft -> cancelled` has no
required fields and is allowed for Admin, so the test posts that directly.
"""
import pathlib
import re
from datetime import datetime, timezone

import pytest

from app.services import release_readiness_service
from tests.runbook_helpers import link, make_plan, make_release, make_task

ALLOWED_IMPORTERS = {
    "app/api/v1/runbooks.py",
    "app/services/my_work_service.py",
    "app/services/runbook_service.py",
    "app/services/runbook_execution_service.py",
    "app/services/runbook_view_service.py",
    "app/services/runbook_schedule_service.py",
}


def test_nothing_outside_the_runbook_imports_it():
    root = pathlib.Path(__file__).resolve().parents[1]
    pattern = re.compile(r"runbook_(service|execution_service|view_service|schedule_service)")
    offenders = []
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWED_IMPORTERS or "/migrations/" in rel:
            continue
        if pattern.search(path.read_text()):
            offenders.append(rel)
    assert offenders == []


@pytest.mark.asyncio
async def test_readiness_is_identical_with_and_without_a_runbook(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    before = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id, now)
    plan = await make_plan(db_session, release, test_environment, anchor=datetime(2026, 10, 1, tzinfo=timezone.utc))
    a = await make_task(db_session, plan, "Failed deploy", status="failed")
    b = await make_task(db_session, plan, "Blocked tests")
    await link(db_session, b, a)
    await db_session.commit()
    after = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id, now)
    assert after.model_dump() == before.model_dump()


@pytest.mark.asyncio
async def test_a_release_with_a_failed_runbook_still_transitions(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=datetime(2026, 10, 1, tzinfo=timezone.utc))
    await make_task(db_session, plan, "Failed deploy", status="failed")
    await db_session.commit()
    # R2: no allowed-transitions route exists; go straight to "cancelled",
    # which the seeded Major template allows from draft with no required
    # fields (unlike "submitted", which 422s on the missing target_date).
    r = await client.post(f"/api/v1/releases/{release.id}/transition", headers=auth_headers,
                          json={"to_state": "cancelled"})
    assert r.status_code == 200, r.text
