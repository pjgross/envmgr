import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.base import get_db
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.deployment import Deployment

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123", "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


async def _release(db, tenant, user, template, name, *, kind="project",
                   scope_deadline=None, target_date=None, actual_date=None):
    r = Release(
        tenant_id=tenant.id, name=name, release_type="Test Major", release_kind=kind,
        lifecycle_template_id=template.id, status="completed", raised_by=user.id,
        scope_deadline=scope_deadline, target_date=target_date, actual_date=actual_date,
    )
    db.add(r)
    await db.flush()
    return r


async def _scope_item(db, tenant, release_id):
    db.add(ReleaseChange(tenant_id=tenant.id, release_id=release_id, title="s", change_kind="story", source="manual"))
    await db.flush()


async def _event(db, tenant, user, release_id, type_name):
    et = (await db.execute(
        select(ReleaseEventType).where(
            ReleaseEventType.tenant_id == tenant.id, ReleaseEventType.name == type_name,
        )
    )).scalar_one_or_none()
    if et is None:
        et = ReleaseEventType(tenant_id=tenant.id, name=type_name)
        db.add(et)
        await db.flush()
    db.add(ReleaseEvent(
        tenant_id=tenant.id, release_id=release_id, event_type_id=et.id,
        description="x", occurred_at=NOW, recorded_by=user.id,
    ))
    await db.flush()


async def _failed_deploy(db, tenant, release_id):
    db.add(Deployment(
        tenant_id=tenant.id, build_id=1, environment_id=1, change_request_id=1,
        event_id=f"evt-{release_id}", deployed_at=NOW, status="failed", release_id=release_id,
    ))
    await db.flush()


async def _deploy(db, tenant, release_id, status):
    db.add(Deployment(
        tenant_id=tenant.id, build_id=1, environment_id=1, change_request_id=1,
        event_id=f"evt-{release_id}-{status}", deployed_at=NOW, status=status, release_id=release_id,
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_scope_churn_cohorts(authed_client, tenant, user, db_session, release_lifecycle_template):
    tpl = release_lifecycle_template
    r1 = await _release(db_session, tenant, user, tpl, "R1",
                        scope_deadline=NOW - timedelta(days=10), target_date=NOW + timedelta(days=1),
                        actual_date=NOW)
    await _scope_item(db_session, tenant, r1.id)
    await _event(db_session, tenant, user, r1.id, "Reschedule Reason")
    await _failed_deploy(db_session, tenant, r1.id)

    await _release(db_session, tenant, user, tpl, "R2",
                   target_date=NOW + timedelta(days=1), actual_date=NOW)

    r3 = await _release(db_session, tenant, user, tpl, "R3",
                        target_date=NOW - timedelta(days=1), actual_date=NOW)
    await _event(db_session, tenant, user, r3.id, "Scope Change")

    await _release(db_session, tenant, user, tpl, "R4-unshipped", actual_date=None)
    await _release(db_session, tenant, user, tpl, "R5-ent", kind="enterprise", actual_date=NOW)
    await _release(db_session, tenant, user, tpl, "R6-old", actual_date=NOW - timedelta(days=400))

    date_from = NOW - timedelta(days=90)
    date_to = NOW + timedelta(days=1)
    resp = await authed_client.get(
        "/api/v1/releases/scope-churn-analytics",
        params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    names = sorted(row["name"] for row in body["releases"])
    assert names == ["R1", "R2", "R3"]

    changed = body["scope_changed"]
    assert changed["count"] == 2
    assert changed["delayed_count"] == 2
    assert changed["delayed_pct"] == 100.0
    assert changed["issue_count"] == 1
    assert changed["issue_pct"] == 50.0

    stable = body["stable"]
    assert stable["count"] == 1
    assert stable["delayed_count"] == 0
    assert stable["issue_count"] == 0
    assert stable["delayed_pct"] == 0.0


@pytest.mark.asyncio
async def test_scope_churn_empty_window(authed_client, tenant, user, db_session, release_lifecycle_template):
    await _release(db_session, tenant, user, release_lifecycle_template, "R", actual_date=NOW)
    date_from = NOW + timedelta(days=10)
    resp = await authed_client.get(
        "/api/v1/releases/scope-churn-analytics",
        params={"date_from": date_from.isoformat()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["releases"] == []
    assert body["scope_changed"]["count"] == 0
    assert body["scope_changed"]["delayed_pct"] == 0.0
    assert body["stable"]["count"] == 0


@pytest.mark.asyncio
async def test_scope_churn_tenant_isolation_and_rolled_back(
    authed_client, tenant, user, db_session, release_lifecycle_template, second_tenant_factory
):
    mine = await _release(db_session, tenant, user, release_lifecycle_template, "MINE",
                          target_date=NOW + timedelta(days=1), actual_date=NOW)
    await _deploy(db_session, tenant, mine.id, "rolled_back")  # rolled_back -> had_issue

    other_tenant, other_user = await second_tenant_factory()
    await _release(db_session, other_tenant, other_user, release_lifecycle_template, "THEIRS", actual_date=NOW)

    resp = await authed_client.get("/api/v1/releases/scope-churn-analytics")
    assert resp.status_code == 200, resp.text
    rows = {r["name"]: r for r in resp.json()["releases"]}
    assert "THEIRS" not in rows           # other tenant's release excluded
    assert "MINE" in rows
    assert rows["MINE"]["had_issue"] is True   # rolled_back deployment counts as an issue
