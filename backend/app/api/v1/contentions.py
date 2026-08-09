"""Escalating a contention, deciding one, and the worklist of both.

A4 ADVISES; IT NEVER ACTS. Nothing in this module transitions, rejects or
reschedules a booking — `test_a_contention_changes_no_booking_behaviour` is the
guard on that promise, and if it fails, A4 has started acting.

THE TWO PERMISSION GATES ARE THE POINT OF THIS FILE. `create_escalation` and
`record_decision` carry no authorization of their own, so:

  - escalating is the owner or a delegate of EITHER contending booking, or an
    Admin (`contention_service.assert_may_escalate`);
  - deciding is the NAMED OWNER, or an Admin (`assert_may_decide`) — the Admin
    path being the escape hatch that makes A4's deliberate lack of an
    edit/withdraw path acceptable.

Cross-tenant is 404, never 403, on every route here.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.contention import (
    EscalationCreate,
    EscalationDecision,
    EscalationRead,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user
from app.db.base import get_db
from app.services import contention_service

router = APIRouter(prefix="/bookings", tags=["contentions"])
escalations_router = APIRouter(prefix="/contention-escalations", tags=["contentions"])


async def _read(db: AsyncSession, escalation, tenant_id: int, now: datetime) -> EscalationRead:
    """One escalation as a response, through the same batch path a page uses.

    Deliberately not a second, single-row implementation: `state`,
    `bookings_live` and the three usernames would then be computed two ways, and
    one test could not guard both.
    """
    views = await contention_service.escalation_views(db, [escalation], tenant_id, now)
    return EscalationRead.from_view(views[escalation.id])


@router.post(
    "/{booking_id}/contentions/{other_id}/escalate",
    response_model=EscalationRead,
    status_code=status.HTTP_201_CREATED,
)
async def escalate_contention(
    booking_id: int,
    other_id: int,
    data: EscalationCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ask a named person to decide this contention by a named date.

    201 the first time, 200 for a re-ask — because ONE CONTENTION HAS ONE
    RECORD, keyed on the unordered pair, and re-asking returns the existing one
    unchanged rather than reassigning its owner or restarting its clock. A UI
    that re-posts on a double click must not create a second contention, nor be
    told its own escalation is an error, so the second call is a success with
    the status code saying nothing was created.

    THE GATE RUNS BEFORE THE LOOKUP, so a bystander cannot use this route to
    discover whether a contention they have no part in has been escalated.
    """
    tenant_id = current_user.active_tenant_id
    now = datetime.now(timezone.utc)
    await contention_service.assert_may_escalate(
        db, booking_id, other_id, tenant_id, current_user
    )

    existing = await contention_service.get_escalation(
        db, booking_id, other_id, tenant_id
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return await _read(db, existing, tenant_id, now)

    escalation = await contention_service.create_escalation(
        db,
        booking_id=booking_id,
        other_booking_id=other_id,
        owner_user_id=data.owner_user_id,
        respond_by=data.respond_by,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    return await _read(db, escalation, tenant_id, now)


@escalations_router.get("", response_model=list[EscalationRead])
async def list_contention_escalations(
    response: Response,
    state: Optional[str] = Query(
        None,
        pattern="^(open|answered|expired)$",
        description=(
            "Filter by computed state. OMIT for everything — there is "
            "deliberately no 'all' value."
        ),
    ),
    owner_user_id: Optional[int] = Query(
        None,
        description=(
            "Filter to the contentions one named person has been asked to "
            "decide. OMIT for everyone's — a filter, not a permission."
        ),
    ),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(contention_service.ESCALATION_SORTS, default="respond_by")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The worklist: contentions somebody has been asked to decide.

    Readable by any tenant member. Who may ANSWER one is a different question,
    settled on the decision route — a decider needs to see the queue they are in,
    and everyone else needs to see that a clash they are party to has been put to
    someone.

    `state` is filtered IN SQL and omission is the "no selection" sentinel. It is
    deliberately not spelled `all`: the frontend's buildParams drops a filter
    whose value is its own sentinel, so a vocabulary containing `all` builds
    byte-identical params for two different states and the grid never refetches.

    `owner_user_id` NARROWS THE QUEUE TO ONE PERSON'S, and is likewise SQL and
    likewise omitted rather than spelled: it is what makes the page usable for
    the reader it was built for, who otherwise pages through everyone else's
    contentions looking for their own username. It is a FILTER, NOT A GATE — the
    whole worklist stays readable, and who may ANSWER a row is settled on the
    decision route. Any user id may be passed (an unknown or cross-tenant one
    simply matches nothing), because the escalation query is tenant-scoped and a
    filter that 404'd on an id would answer a question about another tenant's
    users.

    ONE CLOCK for the whole request — the same `now` decides the filter and every
    row's rendered state, so a page cannot select a row as open and then render
    it expired.
    """
    tenant_id = current_user.active_tenant_id
    now = datetime.now(timezone.utc)
    rows, total = await contention_service.list_escalations(
        db, tenant_id, now=now, page=page, sort=sort, state=state,
        owner_user_id=owner_user_id,
    )
    set_total_count(response, total)
    views = await contention_service.escalation_views(db, rows, tenant_id, now)
    return [EscalationRead.from_view(views[row.id]) for row in rows]


@escalations_router.put("/{escalation_id}/decision", response_model=EscalationRead)
async def decide_contention(
    escalation_id: int,
    data: EscalationDecision,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Record which booking a human said should give way. AND NOTHING ELSE.

    Neither booking's status, dates nor lifecycle is touched. Acting on the
    decision is the owning team's job, through the ordinary transition path —
    which for an A2 group booking moves the whole group atomically, something
    A4 must never reach inside.

    The escalation is read first, tenant-filtered, so a cross-tenant id is 404
    before the owner-or-Admin question is asked — a 403 would confirm the record
    exists.
    """
    tenant_id = current_user.active_tenant_id
    now = datetime.now(timezone.utc)
    escalation = await contention_service.get_escalation_by_id(
        db, escalation_id, tenant_id
    )
    contention_service.assert_may_decide(escalation, current_user)

    decided = await contention_service.record_decision(
        db,
        escalation_id,
        yields_booking_id=data.yields_booking_id,
        notes=data.notes,
        current_user=current_user,
        tenant_id=tenant_id,
    )
    return await _read(db, decided, tenant_id, now)
