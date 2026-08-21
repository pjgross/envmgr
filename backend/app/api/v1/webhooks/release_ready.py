"""GET /api/v1/webhooks/release-ready — release gate readiness.

Read-only advisory endpoint answering "are this release's gates satisfied?".
EnvManager never refuses a deployment; it answers a question the pipeline chose
to ask, and the pipeline enforces.

Auth via the `webhooks:release` API-key scope — deliberately NOT
`webhooks:deployment`, which would silently widen what every existing
deployment key can read to include governance detail (waiver reasons,
approver names, evidence URLs). Always returns 200 OK with a structured body:
HTTP status is not the gate, the same contract can_deploy.py states.

This is one of the two surfaces that call `gate_readiness_service.evaluate` —
the other is `GET /releases/{release_id}/readiness` in releases.py. Both call
the SAME function, so a gate chip and the answer a pipeline obeys cannot
disagree.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_readiness import ReleaseReadinessResponse
from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import gate_readiness_service

router = APIRouter()


@router.get("/release-ready", response_model=ReleaseReadinessResponse)
async def release_ready(
    release_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(api_key_auth(required_scope="webhooks:release")),
):
    return await gate_readiness_service.evaluate(db, release_id, api_key.tenant_id)
