"""DeploymentService — webhook ingest flow.

ingest() is the single transactional entry point. Slug resolution, build
upsert, CR resolution, deployment insert, side effects, event emission —
all in one pass.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.deployment import DeploymentIngestResult, DeploymentWebhookPayload
from app.core.events import publish_event
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.system import System, SubSystem
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import build_service, custom_field_service


ALLOWED_STATUSES = {"pending", "in_progress", "success", "failed", "rolled_back"}


async def _resolve_subsystem(
    db: AsyncSession, tenant_id: int, system_slug: str, subsystem_slug: str
) -> int:
    sys_id = (await db.execute(
        select(System.id).where(
            System.tenant_id == tenant_id,
            System.name == system_slug,
            System.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if sys_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown system_slug '{system_slug}'")
    sub_id = (await db.execute(
        select(SubSystem.id).where(
            SubSystem.tenant_id == tenant_id,
            SubSystem.system_id == sys_id,
            SubSystem.name == subsystem_slug,
            SubSystem.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if sub_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown subsystem_slug '{subsystem_slug}' for system '{system_slug}'")
    return sub_id


async def _resolve_environment(db: AsyncSession, tenant_id: int, slug: str) -> int:
    env_id = (await db.execute(
        select(Environment.id).where(
            Environment.tenant_id == tenant_id,
            Environment.name == slug,
            Environment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if env_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown environment_slug '{slug}'")
    return env_id


async def ingest(
    db: AsyncSession,
    tenant_id: int,
    payload: DeploymentWebhookPayload,
    raised_by_user_id: int,
) -> DeploymentIngestResult:
    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown status '{payload.status}'")

    subsystem_id = await _resolve_subsystem(
        db, tenant_id, payload.system_slug, payload.subsystem_slug,
    )
    environment_id = await _resolve_environment(db, tenant_id, payload.environment_slug)

    # Validate deployment-level custom fields before doing any writes.
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "deployment", payload.deployment_custom_fields or {},
    )

    # Upsert build.
    build = await build_service.upsert_build(
        db, tenant_id=tenant_id, subsystem_id=subsystem_id, data=payload.build,
        release_id=payload.release_id,
    )

    if payload.change_request_id is not None:
        from app.db.models.change_request import ChangeRequest
        cr = (await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == payload.change_request_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if cr is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"change_request_id {payload.change_request_id} not found")
        change_request_id = cr.id
    else:
        from app.services import change_request_service
        cr = await change_request_service.create_code_deployment(
            db,
            tenant_id=tenant_id,
            raised_by=raised_by_user_id,
            title=f"Deploy {payload.build.git_sha[:8]} → {payload.environment_slug}",
            description=f"Auto-created from webhook event {payload.event_id}",
        )
        change_request_id = cr.id

    # Insert deployment.
    completed_at = payload.deployed_at if payload.status in {"success", "failed"} else None
    deployment = Deployment(
        tenant_id=tenant_id,
        build_id=build.id,
        environment_id=environment_id,
        release_id=payload.release_id or build.release_id,
        change_request_id=change_request_id,
        event_id=str(payload.event_id),  # model is String(36) for SQLite compat
        deployer_name=payload.deployer_name,
        deployed_at=payload.deployed_at,
        completed_at=completed_at,
        status=payload.status,
        custom_fields=dict(payload.deployment_custom_fields or {}),
    )
    db.add(deployment)
    await db.flush()

    if payload.status == "success":
        # Audit-trail insert for the installed version.
        version_label = payload.build.build_number or payload.build.git_sha[:8]
        db.add(EnvironmentSubSystemVersion(
            tenant_id=tenant_id,
            environment_id=environment_id,
            subsystem_id=subsystem_id,
            build_identifier=payload.build.git_sha[:12],
            build_fk_id=build.id,
            version_label=version_label,
        ))
        await db.flush()

    await publish_event(
        db,
        event_type={
            "pending": "DeploymentStarted",
            "in_progress": "DeploymentStarted",
            "success": "DeploymentCompleted",
            "failed": "DeploymentFailed",
            "rolled_back": "DeploymentRolledBack",
        }[payload.status],
        aggregate_id=deployment.id,
        aggregate_type="Deployment",
        payload={
            "deployment_id": deployment.id,
            "build_id": build.id,
            "environment_id": environment_id,
            "release_id": deployment.release_id,
            "change_request_id": deployment.change_request_id,
            "status": deployment.status,
        },
        tenant_id=tenant_id,
    )

    return DeploymentIngestResult(
        deployment_id=deployment.id,
        build_id=build.id,
        change_request_id=deployment.change_request_id,
        replayed=False,
    )
