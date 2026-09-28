"""Builders for runbook tests. Every row points at rows these helpers or the
shared fixtures actually created — never a fabricated id (FKs are enforced)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.runbook import RunbookPlan, RunbookTask, RunbookTaskDependency
from app.db.models.system import System
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.release_defaults import seed_release_defaults_for_tenant


async def make_release(db, tenant_id: int, user_id: int, name: str = "R") -> Release:
    tpl = (await db.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id, LifecycleTemplate.name == "Major"))).scalar_one_or_none()
    if tpl is None:
        await seed_release_defaults_for_tenant(db, tenant_id)
        tpl = (await db.execute(select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant_id, LifecycleTemplate.name == "Major"))).scalar_one()
    rel = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(rel)
    await db.flush()
    return rel


async def make_system(db, tenant_id: int, name: str) -> System:
    system = System(tenant_id=tenant_id, name=name)
    db.add(system)
    await db.flush()
    return system


async def attach_system(db, release: Release, system: System, role: str = "changing") -> ReleaseSystem:
    rs = ReleaseSystem(tenant_id=release.tenant_id, release_id=release.id, system_id=system.id, role=role)
    db.add(rs)
    await db.flush()
    return rs


async def make_plan(db, release: Release, environment: Environment, *, anchor: datetime,
                    name: str = "Cutover") -> RunbookPlan:
    plan = RunbookPlan(tenant_id=release.tenant_id, release_id=release.id,
                       environment_id=environment.id, name=name, anchor_start_at=anchor)
    db.add(plan)
    await db.flush()
    return plan


async def make_task(db, plan: RunbookPlan, name: str, *, duration: int = 30,
                    team: Optional[UserGroup] = None, system: Optional[System] = None,
                    fixed_start: Optional[datetime] = None, status: str = "not_started",
                    kind: str = "task") -> RunbookTask:
    task = RunbookTask(tenant_id=plan.tenant_id, plan_id=plan.id, name=name, kind=kind,
                       duration_minutes=duration, team_group_id=team.id if team else None,
                       system_id=system.id if system else None, fixed_start_at=fixed_start,
                       status=status)
    db.add(task)
    await db.flush()
    return task


async def link(db, task: RunbookTask, *preds: RunbookTask) -> None:
    for p in preds:
        db.add(RunbookTaskDependency(tenant_id=task.tenant_id, task_id=task.id, predecessor_task_id=p.id))
    await db.flush()


async def login_headers(client, db, tenant, username: str, role: str) -> tuple[User, dict]:
    user = User(tenant_id=tenant.id, username=username, email=f"{username}@test.com",
                password_hash=get_password_hash("password123"), role=role, is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    resp = await client.post("/api/v1/auth/login", json={
        "username": username, "password": "password123", "tenant_slug": tenant.slug})
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}
