"""Release Templates API — CRUD + instantiate."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import release_template_service, project_service
from app.api.v1.schemas.release_template import (
    ReleaseTemplateCreate,
    ReleaseTemplateUpdate,
    ReleaseTemplateRead,
    ReleaseTemplateInstantiate,
)
from app.api.v1.schemas.release import ReleaseRead

router = APIRouter(prefix="/release-templates", tags=["Release Templates"])


@router.get("", response_model=list[ReleaseTemplateRead])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_template_service.list_templates(db, current_user.active_tenant_id)


@router.post("", response_model=ReleaseTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: ReleaseTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_template_service.create_template(db, data, current_user.active_tenant_id)


@router.get("/{template_id}", response_model=ReleaseTemplateRead)
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_template_service.get_template(db, template_id, current_user.active_tenant_id)


@router.put("/{template_id}", response_model=ReleaseTemplateRead)
async def update_template(
    template_id: int,
    data: ReleaseTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_template_service.update_template(
        db, template_id, data, current_user.active_tenant_id
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_template_service.delete_template(
        db, template_id, current_user.active_tenant_id
    )


@router.post("/{template_id}/instantiate", response_model=ReleaseRead, status_code=status.HTTP_201_CREATED)
async def instantiate_template(
    template_id: int,
    data: ReleaseTemplateInstantiate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a release (with phases and gates) from this template."""
    release = await release_template_service.instantiate(
        db, template_id, data, current_user.active_tenant_id, current_user.id
    )
    resp = ReleaseRead.model_validate(release)
    if release.owning_project_id is not None:
        # release_template_service.instantiate never sets owning_project_id
        # today, so this is unreachable in practice — but the day a template
        # can carry one, this must not silently render null the way the bare
        # ORM object did (see app/api/v1/releases.py's _release_with_permissions
        # for the same lookup on every other ReleaseRead producer).
        names = await project_service.get_project_names(
            db, {release.owning_project_id}, current_user.active_tenant_id
        )
        resp.owning_project_name = names.get(release.owning_project_id)
    return resp
