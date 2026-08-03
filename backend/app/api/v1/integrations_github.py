"""GitHub integration: connect, poll, status, disconnect."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_tenant_admin
from app.db.base import get_db
from app.services import github_oauth_service
from app.services.github_oauth_service import GitHubNotConfigured

router = APIRouter(prefix="/integrations/github", tags=["integrations"])


class ConnectStarted(BaseModel):
    handle: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class IntegrationStatus(BaseModel):
    connected: bool
    github_login: str | None = None
    connected_at: str | None = None


@router.get("", response_model=IntegrationStatus)
async def github_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Never returns the token — only whether one is held, and whose it is."""
    return await github_oauth_service.get_status(db, current_user.active_tenant_id)


@router.post("/connect", response_model=ConnectStarted)
async def github_connect(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    try:
        return await github_oauth_service.start_device_flow(
            db, current_user.active_tenant_id, current_user.id
        )
    except GitHubNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.post("/connect/{handle}/poll")
async def github_connect_poll(
    handle: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    try:
        return await github_oauth_service.poll_device_flow(
            db, current_user.active_tenant_id, current_user.id, handle
        )
    except GitHubNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.delete("")
async def github_disconnect(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Local only. GitHub's own grant is unaffected — the UI must say so."""
    await github_oauth_service.disconnect(db, current_user.active_tenant_id)
    return {"disconnected": True}
