"""GET /pir-actions — every PIR action in the tenant, in one place.

A PIR action is a process fix that outlives the release it came from. Inside the
release's own tab it is invisible the moment attention moves on, which is the
classic reason PIR actions never get done. This page is the point of the feature.

Readable by any tenant member, deliberately — the same call the contention and
decommission worklists made. Who may EDIT an action is settled on the PIR, not by
hiding the list.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.pir_finding import PirActionRow
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.pir_finding import ACTION_STATUSES, PirAction
from app.db.models.release import Release
from app.db.models.user import User
from app.services import pir_finding_service

router = APIRouter(prefix="/pir-actions", tags=["pir"])

# `release` and `owner` sort by the NAME the row renders, not by the id — sorting
# a column of names by an integer nobody can see is indistinguishable from no
# sort at all. Both are single columns on a joined table, so both are legitimate
# whitelist entries; nothing computed in Python after the query is here.
PIR_ACTION_SORTS = {
    "title": PirAction.title,
    "status": PirAction.status,
    "due_date": PirAction.due_date,
    "created_at": PirAction.created_at,
    "release": Release.name,
    "owner": User.username,
}


@router.get("", response_model=list[PirActionRow])
async def list_pir_actions(
    response: Response,
    status_: Optional[str] = Query(None, alias="status"),
    owner_id: Optional[int] = Query(None),
    overdue: Optional[bool] = Query(None),
    release_id: Optional[int] = Query(None),
    incident_id: Optional[int] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(PIR_ACTION_SORTS, default="due_date")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # An unknown status is a 422, never a silently ignored filter: a page that
    # asked for one slice and was handed the whole set renders it as though it
    # were the slice. The empty string is an unknown status like any other.
    if status_ is not None and status_ not in ACTION_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(ACTION_STATUSES)}")
    rows, total = await pir_finding_service.list_actions(
        db,
        current_user.active_tenant_id,
        now=datetime.now(timezone.utc),
        status=status_,
        owner_id=owner_id,
        overdue=overdue,
        release_id=release_id,
        incident_id=incident_id,
        page=page,
        sort=sort,
    )
    set_total_count(response, total)
    return rows
