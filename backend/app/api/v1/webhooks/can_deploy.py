"""GET /api/v1/webhooks/can-deploy — deployment preflight gate.

Read-only advisory endpoint that answers "may I deploy now?" given an
(environment_slug, subsystem_slug) pair plus optional claim tokens
(release_id / booking_id) that can unlock an exclusive-booking blocker.

Auth via the existing `webhooks:deployment` API-key scope. Always returns
200 OK with a structured body — HTTP status is not the gate.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.preflight import CanDeployResponse
from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import preflight_service


router = APIRouter()


@router.get("/can-deploy", response_model=CanDeployResponse)
async def can_deploy(
    environment_slug: str = Query(...),
    subsystem_slug: str = Query(...),
    release_id: int | None = Query(None),
    booking_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(api_key_auth(required_scope="webhooks:deployment")),
):
    return await preflight_service.evaluate(
        db,
        tenant_id=api_key.tenant_id,
        environment_slug=environment_slug,
        subsystem_slug=subsystem_slug,
        release_id=release_id,
        booking_id=booking_id,
    )
