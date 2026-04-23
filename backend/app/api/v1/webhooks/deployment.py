"""POST /api/v1/webhooks/deployment — CI/CD deployment ingestion."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import deployment_service
from app.api.v1.schemas.deployment import (
    DeploymentIngestResult,
    DeploymentWebhookPayload,
)


router = APIRouter()


@router.post("/deployment", response_model=DeploymentIngestResult)
async def ingest_deployment(
    payload: DeploymentWebhookPayload,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(api_key_auth(required_scope="webhooks:deployment")),
):
    return await deployment_service.ingest(
        db,
        tenant_id=api_key.tenant_id,
        payload=payload,
        raised_by_user_id=api_key.created_by,
    )
