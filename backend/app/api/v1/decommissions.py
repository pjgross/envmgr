"""Initiating a decommission, and reading the one live (or most recent) record.

Cross-tenant is 404, never 403, on every route here — following
`app/api/v1/contentions.py`. `environment_decommission_service.get_environment`
(really `environment_service.get_environment`, tenant-filtered) is what makes
that true: a foreign-tenant id simply never matches the query, so the 404 and
the "doesn't exist" case are indistinguishable to the caller, which is the
point.

Three routes on this pair of routers, not two:

  - POST .../decommission -- initiate.
  - GET  .../decommission -- the live record, or the most recent terminal
    one when there is no live record, or null. A 404 for "this environment
    has never been decommissioned" would make the panel's ordinary case an
    error path; null is the answer, and the panel renders its initiate
    control from it.
  - GET  /decommissions -- Task 9's worklist, every decommission this tenant
    can see, live and terminal alike. Cross-tenant is simply absent from the
    result here rather than 404 — there is no single id to be cagey about.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.decommission import (
    AttestationCreate, AttestationRead, CancelRequest, DecommissionCreate,
    DecommissionRead, DecommissionWorklistRow, ExtensionDecision,
    ExtensionRequest, RemainingBookingSummary, TeardownRead,
)
from app.core.decommission_states import DECOMMISSION_STATES
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.environment_decommission import EnvironmentDecommission
from app.services import booking_service, environment_decommission_service

router = APIRouter(prefix="/environments", tags=["decommissions"])
extensions_router = APIRouter(prefix="/decommissions", tags=["decommissions"])


def _to_read(row: EnvironmentDecommission, now: datetime) -> DecommissionRead:
    """One decommission as a response. `state` is computed here, never
    `model_validate`d, because there is no state column to validate from —
    see the schema module docstring."""
    return DecommissionRead(
        id=row.id,
        environment_id=row.environment_id,
        reason=row.reason,
        warned_at=row.warned_at,
        scheduled_teardown_at=row.scheduled_teardown_at,
        initiated_by=row.initiated_by,
        extension_requested_at=row.extension_requested_at,
        extension_reason=row.extension_reason,
        extension_until=row.extension_until,
        extension_decided_at=row.extension_decided_at,
        extension_granted=row.extension_granted,
        torn_down_at=row.torn_down_at,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        state=environment_decommission_service.decommission_state(row, now),
    )


@extensions_router.get("", response_model=list[DecommissionWorklistRow])
async def list_decommission_worklist(
    response: Response,
    state: Optional[str] = Query(
        None,
        pattern="^(" + "|".join(DECOMMISSION_STATES) + ")$",
        description=(
            "Filter by computed state. OMIT for everything — there is "
            "deliberately no 'all' value."
        ),
    ),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(
            environment_decommission_service.DECOMMISSION_SORTS,
            default="scheduled_teardown_at",
        )
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The worklist: every decommission this tenant can see — live and
    terminal alike, following `contentions_router`'s worklist (an escalation
    outlives its bookings; a decommission's history is as much the record as
    its live state, and nothing here filters on liveness).

    Readable by any tenant member — there is no gate here beyond tenant
    scoping. Who may ACT on a row (extend, sign, tear down, cancel) is settled
    on the routes below, each through `assert_may_run` / `assert_may_defend`.

    ONE CLOCK decides both the `state` filter and every rendered row's
    state — taken once, here, and threaded through `list_decommissions` and
    `decommission_views` alike, so a row cannot be selected as `due` and
    rendered `warned`.
    """
    tenant_id = current_user.active_tenant_id
    now = datetime.now(timezone.utc)
    rows, total = await environment_decommission_service.list_decommissions(
        db, tenant_id, state=state, page=page, sort=sort, now=now,
    )
    set_total_count(response, total)
    views = await environment_decommission_service.decommission_views(
        db, rows, tenant_id, now
    )
    return [DecommissionWorklistRow.from_view(views[row.id]) for row in rows]


@router.post(
    "/{environment_id}/decommission",
    response_model=DecommissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_decommission(
    environment_id: int,
    data: DecommissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # One clock for the whole request: the stored row and its rendered state
    # must come from the same instant, or a row created at 23:59:59 could
    # render 'due' a moment later purely from re-reading the wall clock. This
    # is the ONLY `datetime.now()` call anywhere in this request's path —
    # `initiate` and `get_live` both take `now` as a required parameter
    # precisely so a second clock cannot be reintroduced downstream.
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    row = await environment_decommission_service.initiate(
        db,
        tenant_id,
        environment_id,
        current_user,
        reason=data.reason,
        scheduled_teardown_at=data.scheduled_teardown_at,
        now=now,
    )
    return _to_read(row, now)


@router.get(
    "/{environment_id}/decommission",
    response_model=Optional[DecommissionRead],
)
async def get_decommission(
    environment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    # 404 across tenants, never 403 — resolving the environment first is what
    # makes a foreign-tenant id behave identically to one that never existed.
    await environment_decommission_service.get_environment(db, environment_id, tenant_id)

    row = await environment_decommission_service.get_live(db, tenant_id, environment_id, now)
    if row is None:
        row = await environment_decommission_service.get_most_recent(
            db, tenant_id, environment_id
        )
    if row is None:
        return None
    return _to_read(row, now)


@extensions_router.post(
    "/{decommission_id}/extension",
    response_model=DecommissionRead,
)
async def request_decommission_extension(
    decommission_id: int,
    data: ExtensionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The owner asking for more time. `get_decommission_by_id` is
    tenant-filtered, so a cross-tenant id is 404 before `assert_may_defend`
    ever runs — a 403 would confirm the record exists."""
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    decommission = await environment_decommission_service.get_decommission_by_id(
        db, decommission_id, tenant_id
    )
    row = await environment_decommission_service.request_extension(
        db, decommission, current_user,
        reason=data.reason, until=data.until, now=now,
    )
    return _to_read(row, now)


@extensions_router.post(
    "/{decommission_id}/extension/decision",
    response_model=DecommissionRead,
)
async def decide_decommission_extension(
    decommission_id: int,
    data: ExtensionDecision,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The operating team's answer — `assert_may_run`, deliberately not the
    owner-side gate the request route uses."""
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    decommission = await environment_decommission_service.get_decommission_by_id(
        db, decommission_id, tenant_id
    )
    row = await environment_decommission_service.decide_extension(
        db, decommission, current_user, granted=data.granted, now=now,
    )
    return _to_read(row, now)


@extensions_router.post(
    "/{decommission_id}/attestations",
    response_model=AttestationRead,
    status_code=status.HTTP_201_CREATED,
)
async def sign_decommission_attestation(
    decommission_id: int,
    data: AttestationCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The operating team confirming one checklist step happened —
    `assert_may_run`, the same gate as initiate/teardown/cancel."""
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    decommission = await environment_decommission_service.get_decommission_by_id(
        db, decommission_id, tenant_id
    )
    row = await environment_decommission_service.sign_attestation(
        db, decommission, current_user,
        step_key=data.step_key, reference=data.reference, notes=data.notes,
        now=now,
    )
    return row


@extensions_router.post(
    "/{decommission_id}/teardown",
    response_model=TeardownRead,
)
async def tear_down_decommission(
    decommission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """THE ONE ACTING ROUTE. Sets `environment.status = DECOMMISSIONED` and
    reports — without touching — any bookings still on the calendar for this
    environment."""
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    decommission = await environment_decommission_service.get_decommission_by_id(
        db, decommission_id, tenant_id
    )
    row = await environment_decommission_service.tear_down(
        db, decommission, current_user, now=now
    )
    # Task 8 carried-forward fix: was booking_service.list_bookings with no
    # status filter and no page — every non-deleted booking, drafts included,
    # unbounded. Scoped to genuinely live bookings (excludes only the
    # TERMINAL ones — rejected/closed — so a draft still shows) and bounded.
    # See list_live_bookings' own docstring for why draft stays in.
    remaining = await booking_service.list_live_bookings(db, tenant_id, row.environment_id)
    base = _to_read(row, now)
    return TeardownRead(
        **base.model_dump(),
        remaining_bookings=[
            RemainingBookingSummary.model_validate(b) for b in remaining
        ],
    )


@extensions_router.post(
    "/{decommission_id}/cancel",
    response_model=DecommissionRead,
)
async def cancel_decommission(
    decommission_id: int,
    data: CancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """THE ESCAPE HATCH — always available to Admin. Sets only the three
    cancel fields; `environment.status` is never touched here."""
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    decommission = await environment_decommission_service.get_decommission_by_id(
        db, decommission_id, tenant_id
    )
    row = await environment_decommission_service.cancel(
        db, decommission, current_user, reason=data.reason, now=now,
    )
    return _to_read(row, now)
