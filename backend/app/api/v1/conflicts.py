from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, pagination, set_total_count
from app.db.base import get_db
from app.core.security import get_current_user
from app.services import conflict_service
from app.api.v1.schemas.conflict import (
    ConflictAckUpsert,
    ConflictAckRead,
    ConflictItem,
    ReceivedFeedbackItem,
    UserRef,
    RequestContextRef,
)
from app.api.v1.schemas.booking_request import EnvBookingSummary

router = APIRouter(prefix="/bookings", tags=["conflicts"])


@router.get("/{booking_id}/conflicts", response_model=list[ConflictItem])
async def list_conflicts(
    booking_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    page: Page = Depends(pagination()),
):
    others, total = await conflict_service.list_conflicts(
        db, booking_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    items: list[ConflictItem] = []
    for c in others:
        ack = await conflict_service.get_ack(
            db, booking_id, c.booking.id, current_user.active_tenant_id
        )
        items.append(ConflictItem(
            other_booking=EnvBookingSummary(
                id=c.booking.id,
                environment_id=c.booking.environment_id,
                environment_name=c.environment_name,
                project_name=c.project_name,
                start_date=c.booking.start_date,
                end_date=c.booking.end_date,
                status=c.booking.status,
            ),
            ack=ConflictAckRead.model_validate(ack) if ack else None,
        ))
    return items


@router.put("/{booking_id}/conflicts/{other_id}/ack", response_model=ConflictAckRead)
async def ack_conflict(
    booking_id: int,
    other_id: int,
    data: ConflictAckUpsert,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    ack = await conflict_service.upsert_ack(
        db, booking_id, other_id,
        willing_to_share=data.willing_to_share,
        notes=data.notes,
        current_user=current_user,
        tenant_id=current_user.active_tenant_id,
    )
    return ConflictAckRead.model_validate(ack)


@router.get(
    "/{booking_id}/received-feedback",
    response_model=list[ReceivedFeedbackItem],
)
async def list_received_feedback(
    booking_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows, total = await conflict_service.list_received_feedback(
        db, booking_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [
        ReceivedFeedbackItem(
            willing_to_share=r.ack.willing_to_share,
            notes=r.ack.notes,
            acknowledged_at=r.ack.acknowledged_at,
            acknowledged_by=UserRef.model_validate(r.acknowledged_by),
            source_booking=EnvBookingSummary(
                id=r.source_booking.id,
                environment_id=r.source_booking.environment_id,
                project_name=r.source_request.project_name,
                start_date=r.source_booking.start_date,
                end_date=r.source_booking.end_date,
                status=r.source_booking.status,
            ),
            source_request=RequestContextRef(
                id=r.source_request.id,
                project_name=r.source_request.project_name,
                notes=r.source_request.notes,
                context_tag=r.source_request.context_tag,
                exclusive_use_requested=r.source_request.exclusive_use_requested,
                booked_by=UserRef.model_validate(r.booked_by),
            ),
        )
        for r in rows
    ]
