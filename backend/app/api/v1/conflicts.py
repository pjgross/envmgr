from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import conflict_service
from app.api.v1.schemas.conflict import ConflictAckUpsert, ConflictAckRead, ConflictItem
from app.api.v1.schemas.booking_request import EnvBookingSummary

router = APIRouter(prefix="/bookings", tags=["conflicts"])


@router.get("/{booking_id}/conflicts", response_model=list[ConflictItem])
async def list_conflicts(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    others = await conflict_service.list_conflicts(
        db, booking_id, current_user.active_tenant_id
    )
    items: list[ConflictItem] = []
    for o in others:
        ack = await conflict_service.get_ack(db, booking_id, o.id, current_user.active_tenant_id)
        items.append(ConflictItem(
            other_booking=EnvBookingSummary(
                id=o.id, environment_id=o.environment_id,
                start_date=o.start_date, end_date=o.end_date, status=o.status,
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
