from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, pagination, set_total_count
from app.db.base import get_db
from app.core.security import get_current_user
from app.services import (
    agreement_gap_service, conflict_service, contention_service,
    environment_group_service,
)
from app.api.v1.schemas.conflict import (
    ConflictAckUpsert,
    ConflictAckRead,
    ConflictItem,
    ReceivedFeedbackItem,
    UserRef,
    RequestContextRef,
)
from app.api.v1.schemas.contention import ContentionRead
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
    # Batch-resolved, same as every other EnvBookingSummary/BookingResponse
    # call site (bookings.py, booking_requests.py) — deliberately not filtering
    # deleted_at so an archived group still renders its name here too.
    group_names = await environment_group_service.get_group_names(
        db,
        {c.booking.environment_group_id for c in others if c.booking.environment_group_id is not None},
        current_user.active_tenant_id,
    )
    # A3's usage-agreement warning, batched over the page the same way the group
    # names above are. EnvBookingSummary requires these two fields precisely so
    # that this construction site — which does not go through
    # booking_requests._summaries — cannot quietly answer differently about a
    # booking than GET /bookings does.
    gaps = await agreement_gap_service.gap_warnings_for_bookings(
        db, [c.booking for c in others], current_user.active_tenant_id
    )
    # Whether each OTHER booking's owner has unanswered conflicts of their own —
    # a different question from `ack` below, which is whether WE have answered
    # about them. Batched for the same reason the gaps are.
    unanswered = await conflict_service.bookings_with_unacknowledged_conflicts(
        db, [c.booking.id for c in others], current_user.active_tenant_id
    )
    # A4's verdict and its escalation, BATCHED OVER THE PAGE — four calls
    # (verdicts_for_pairs, escalations_for_pairs and escalation_views below,
    # plus booking_labels further down) beside the three above (group_names,
    # gaps, unanswered), never one pair at a time. Three sub-projects have now
    # added a field to this endpoint and every per-row form has had to be undone.
    # NOT the whole story for this endpoint: `conflict_service.get_ack` in the
    # loop below is still one query per row. That is pre-existing, not A4's, and
    # is the only un-batched lookup left here — do not read the rule above as a
    # statement that the endpoint as a whole is batched.
    #
    # The pairs are keyed AS GIVEN, `(subject, other)`, which is the contract
    # both batch functions state: `escalations_for_pairs` normalises internally,
    # so the caller must NOT pre-normalise or half its lookups would miss.
    now = datetime.now(timezone.utc)
    pairs = [(booking_id, c.booking.id) for c in others]
    verdicts = await contention_service.verdicts_for_pairs(
        db, pairs, current_user.active_tenant_id
    )
    escalations = await contention_service.escalations_for_pairs(
        db, pairs, current_user.active_tenant_id
    )
    # The liveness and the names an EscalationRead needs, batched the same way.
    # `views`, not `escalation_views` — a local of the service function's own
    # name makes `views.get(...)` below read as a call into the service, and a
    # later edit dropping the `contention_service.` prefix would fail
    # confusingly. Matches `contentions.py`.
    views = await contention_service.escalation_views(
        db, escalations.values(), current_user.active_tenant_id, now
    )
    # WHICH PROJECTS ARE ARGUING, by name. A verdict names a winning BOOKING and
    # the screen has to name the winning PROJECT — and no other field here can
    # supply it: `EnvBookingSummary.project_name` below is the request's free
    # text ("Purpose"), not the linked project. Batched over the page beside the
    # six batches above (group_names, gaps, unanswered, verdicts, escalations,
    # views), never per row.
    #
    # THE SUBJECT IS IN THE SET TOO. Its own project is one half of every line
    # on this page, and it is not among `others`.
    labels = await contention_service.booking_labels(
        db,
        [booking_id, *(c.booking.id for c in others)],
        current_user.active_tenant_id,
    )
    subject_project_name = labels.get(
        booking_id, contention_service.NO_LABEL
    ).project_name
    items: list[ConflictItem] = []
    for c in others:
        ack = await conflict_service.get_ack(
            db, booking_id, c.booking.id, current_user.active_tenant_id
        )
        escalation = escalations.get((booking_id, c.booking.id))
        items.append(ConflictItem(
            other_booking=EnvBookingSummary(
                id=c.booking.id,
                environment_id=c.booking.environment_id,
                environment_name=c.environment_name,
                project_name=c.project_name,
                start_date=c.booking.start_date,
                end_date=c.booking.end_date,
                status=c.booking.status,
                environment_group_id=c.booking.environment_group_id,
                environment_group_name=group_names.get(c.booking.environment_group_id),
                **agreement_gap_service.gap_fields(gaps.get(c.booking.id)),
                **conflict_service.conflict_fields(c.booking.id in unanswered),
            ),
            contention=ContentionRead.from_verdict(
                verdicts[(booking_id, c.booking.id)],
                views.get(escalation.id) if escalation else None,
                subject_project_name,
                labels.get(c.booking.id, contention_service.NO_LABEL).project_name,
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
    group_names = await environment_group_service.get_group_names(
        db,
        {r.source_booking.environment_group_id for r in rows if r.source_booking.environment_group_id is not None},
        current_user.active_tenant_id,
    )
    gaps = await agreement_gap_service.gap_warnings_for_bookings(
        db, [r.source_booking for r in rows], current_user.active_tenant_id
    )
    unanswered = await conflict_service.bookings_with_unacknowledged_conflicts(
        db, [r.source_booking.id for r in rows], current_user.active_tenant_id
    )
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
                environment_group_id=r.source_booking.environment_group_id,
                environment_group_name=group_names.get(r.source_booking.environment_group_id),
                **agreement_gap_service.gap_fields(gaps.get(r.source_booking.id)),
                **conflict_service.conflict_fields(r.source_booking.id in unanswered),
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
