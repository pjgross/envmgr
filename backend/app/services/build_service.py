"""BuildService — upsert builds by (tenant, subsystem, git_sha, build_number)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.build import BuildPayload
from app.db.models.build import Build
from app.services import custom_field_service


async def upsert_build(
    db: AsyncSession,
    tenant_id: int,
    subsystem_id: int,
    data: BuildPayload,
    release_id: int | None = None,
) -> Build:
    """Insert or update a Build row, keyed on
    (tenant_id, subsystem_id, git_sha, build_number).

    Pipeline steps, jira tickets, custom fields, and finished_at are
    replaced wholesale on update — callers own the canonical view."""
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "build", data.custom_fields or {},
    )

    existing = (
        await db.execute(
            select(Build).where(
                Build.tenant_id == tenant_id,
                Build.subsystem_id == subsystem_id,
                Build.git_sha == data.git_sha,
                Build.build_number == data.build_number,
                Build.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        build = Build(
            tenant_id=tenant_id,
            subsystem_id=subsystem_id,
            release_id=release_id,
            git_sha=data.git_sha,
            git_branch=data.git_branch,
            build_number=data.build_number,
            commit_timestamp=data.commit_timestamp,
            build_started_at=data.build_started_at,
            build_finished_at=data.build_finished_at,
            jira_tickets=list(data.jira_tickets or []),
            pipeline_steps=[s.model_dump(mode="json") for s in data.pipeline_steps],
            custom_fields=dict(data.custom_fields or {}),
        )
        db.add(build)
        await db.flush()
        return build

    existing.git_branch = data.git_branch
    existing.build_started_at = data.build_started_at
    existing.build_finished_at = data.build_finished_at
    existing.jira_tickets = list(data.jira_tickets or [])
    existing.pipeline_steps = [s.model_dump(mode="json") for s in data.pipeline_steps]
    existing.custom_fields = dict(data.custom_fields or {})
    if release_id is not None:
        existing.release_id = release_id
    await db.flush()
    return existing
