"""Phase 9 C5a — cutover runbook routes. Thin over the runbook services.

Mounted in main.py under /api/v1. Paths are /releases/{id}/runbooks,
/runbooks/{id}… and /runbook-tasks/{id}… — no literal segment follows a
catch-all in any router it shares a prefix with.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.runbook import (
    PredecessorsUpdate, RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead,
    RunbookTaskCreate, RunbookTaskEventRead, RunbookTaskRead, RunbookTaskUpdate, TransitionRequest,
)
from app.core.pagination import Page, pagination, set_total_count
from app.core.security import Role, get_current_user, require_role
from app.db.base import get_db
from app.services import (
    gate_waiver_service, release_service, runbook_execution_service, runbook_service, runbook_view_service,
)

router = APIRouter(tags=["Runbooks"])
_manager = require_role(Role.RELEASE_MANAGER)   # Admin and master admin pass too

# FastAPI 0.141 added `Depends(..., scope=)`. A yield-dependency with no scope
# defaults to "request": its post-yield code (get_db's commit/rollback/close)
# runs after `await response(scope, receive, send)` in
# fastapi/routing.py's `request_response()` (site-packages/fastapi/routing.py:145),
# i.e. AFTER the response bytes are already on the wire — so a client's very
# next request can race the commit and read stale data (this bit the live dev
# server: a transition's 200 came back before its own write was committed).
# `scope="function"` moves the post-yield code inside the *inner*
# `async with AsyncExitStack() as function_stack:` block (routing.py:142-145),
# which closes BEFORE `await response(...)` runs, closing that race for every
# route in this router.
#
# `get_current_user` (app/core/security.py) has its own bare
# `db: AsyncSession = Depends(get_db)` — scope=None, so it computes to
# "request" (fastapi/dependencies/models.py:_get_computed_scope, since get_db
# is an async generator). The dependency cache key is
# `(call, scopes, computed_scope)` (models.py:_get_cache_key), and scope is
# part of that key — so our `scope="function"` Depends(get_db, ...) below is
# NOT the same cache entry as get_current_user's, meaning each request opens
# TWO separate sessions/transactions here: one (function-scoped) for this
# router's own reads and writes, one (request-scoped, read-only — it only
# loads the caller's User row) inside get_current_user. That is fine: nothing
# in this router writes through get_current_user's session, and the two
# scopes are still nested (function_stack sits inside request_stack in
# routing.py), so an exception raised in the route still unwinds BOTH — a
# raised HTTPException propagates through the AsyncExitStack machinery to
# every entered dependency regardless of scope, and get_db's own
# `except Exception: rollback(); raise` re-raises rather than swallowing it,
# so the function-scoped session rolls back correctly before the exception
# reaches FastAPI's error-response machinery. Verified by reading
# fastapi/routing.py's `request_response()` (function_stack nested inside
# request_stack) and by
# test_a_failed_task_create_rolls_back_the_flushed_task in
# tests/test_runbook_api.py (create_task flushes the new task, assigning it
# an id, before validating predecessor_ids; an invalid id 409s after that
# flush, and the row must not survive).
_db = Depends(get_db, scope="function")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _read(db, plan, user) -> RunbookRead:
    return await runbook_view_service.read(db, plan, user.active_tenant_id, user, _now())


@router.get("/releases/{release_id}/runbooks", response_model=list[RunbookPlanRead])
async def list_runbooks(release_id: int, response: Response, page: Page = Depends(pagination()),
                        db: AsyncSession = _db, current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    plans, total = await runbook_service.list_plans(db, release_id, tenant_id, page)
    set_total_count(response, total)
    return await runbook_view_service.plan_reads(db, plans, tenant_id)


@router.post("/releases/{release_id}/runbooks", response_model=RunbookRead, status_code=status.HTTP_201_CREATED)
async def create_runbook(release_id: int, data: RunbookPlanCreate, db: AsyncSession = _db,
                         current_user=Depends(_manager)):
    plan = await runbook_service.create_plan(db, release_id, current_user.active_tenant_id, data)
    return await _read(db, plan, current_user)


@router.get("/runbooks/{plan_id}", response_model=RunbookRead)
async def get_runbook(plan_id: int, db: AsyncSession = _db, current_user=Depends(get_current_user)):
    plan = await runbook_service.get_plan(db, plan_id, current_user.active_tenant_id)
    return await _read(db, plan, current_user)


@router.patch("/runbooks/{plan_id}", response_model=RunbookRead)
async def update_runbook(plan_id: int, data: RunbookPlanUpdate, db: AsyncSession = _db,
                         current_user=Depends(_manager)):
    plan = await runbook_service.get_plan(db, plan_id, current_user.active_tenant_id)
    await runbook_service.update_plan(db, plan, data)
    return await _read(db, plan, current_user)


@router.delete("/runbooks/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_runbook(plan_id: int, db: AsyncSession = _db, current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    plan = await runbook_service.get_plan(db, plan_id, tenant_id)
    await runbook_service.delete_plan(db, plan, tenant_id)


@router.post("/runbooks/{plan_id}/tasks", response_model=RunbookTaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(plan_id: int, data: RunbookTaskCreate, db: AsyncSession = _db,
                      current_user=Depends(_manager)):
    """Returns the new task's row from the composite (schedule and
    allowed_transitions included), not a second task shape."""
    tenant_id = current_user.active_tenant_id
    plan = await runbook_service.get_plan(db, plan_id, tenant_id)
    task = await runbook_service.create_task(db, plan, tenant_id, data)
    composite = await _read(db, plan, current_user)
    return next(t for t in composite.tasks if t.id == task.id)


@router.patch("/runbook-tasks/{task_id}", response_model=RunbookRead)
async def update_task(task_id: int, data: RunbookTaskUpdate, db: AsyncSession = _db,
                      current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.update_task(db, task, plan, tenant_id, data)
    return await _read(db, plan, current_user)


@router.delete("/runbook-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: AsyncSession = _db, current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, _ = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.delete_task(db, task, tenant_id)


@router.put("/runbook-tasks/{task_id}/predecessors", response_model=RunbookRead)
async def set_predecessors(task_id: int, data: PredecessorsUpdate, db: AsyncSession = _db,
                           current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.set_predecessors(db, task, plan, tenant_id, data.predecessor_ids)
    return await _read(db, plan, current_user)


@router.post("/runbook-tasks/{task_id}/transition", response_model=RunbookRead)
async def transition_task(task_id: int, data: TransitionRequest, db: AsyncSession = _db,
                          current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    now = _now()
    await runbook_execution_service.transition(db, task, plan, tenant_id, current_user, data, now)
    return await runbook_view_service.read(db, plan, tenant_id, current_user, now)


@router.get("/runbook-tasks/{task_id}/events", response_model=list[RunbookTaskEventRead])
async def task_events(task_id: int, response: Response, page: Page = Depends(pagination()),
                      db: AsyncSession = _db, current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    await runbook_service.get_task(db, task_id, tenant_id)          # 404 across tenants
    rows, total = await runbook_execution_service.list_events(db, task_id, tenant_id, page)
    set_total_count(response, total)
    names = await gate_waiver_service.usernames_for(db, {r.by_user_id for r in rows if r.by_user_id})
    return [RunbookTaskEventRead(id=r.id, from_status=r.from_status, to_status=r.to_status, at=r.at,
                                 recorded_at=r.recorded_at, by_username=names.get(r.by_user_id), note=r.note)
            for r in rows]
