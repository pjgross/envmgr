"""Projects — CRUD plus the counts the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same reasoning as environment_tier_service and user_group_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.project import ProjectCreate, ProjectUpdate, UsageAgreementCreate
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.project import Project, UsageAgreement
from app.db.models.user_group import UserGroup


@dataclass
class ProjectView:
    """A project plus the labels a UI needs without extra round-trips,
    following environment_service.EnvironmentView."""

    project: Project
    team_group_name: Optional[str]
    environment_count: int


def _environment_count_clause(tenant_id: int):
    return (
        select(func.count(UsageAgreement.id))
        .where(
            UsageAgreement.project_id == Project.id,
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
        )
        .correlate(Project)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    """The one select carrying a project's display labels.

    The join is tenant-qualified — defence in depth matching
    environment_service._view_query: a malformed row must not surface another
    tenant's name. It does NOT filter the group's deleted_at, so an archived
    team still renders its name rather than blanking.
    """
    return (
        select(Project, UserGroup.name, _environment_count_clause(tenant_id))
        .outerjoin(
            UserGroup,
            and_(
                UserGroup.id == Project.team_group_id,
                UserGroup.tenant_id == tenant_id,
            ),
        )
        .where(Project.tenant_id == tenant_id, Project.deleted_at.is_(None))
    )


def _to_view(row) -> ProjectView:
    project, team_name, env_count = row
    return ProjectView(
        project=project, team_group_name=team_name, environment_count=env_count
    )


PROJECT_SORTS = {
    "name": Project.name,
    "code": Project.code,
    "created_at": Project.created_at,
}


async def list_projects(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> tuple[list[ProjectView], int]:
    """Projects for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter — see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    if search:
        query = query.where(Project.name.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.where(Project.is_active.is_(is_active))
    # Names are unique per tenant, but apply_sort folds case, so two names
    # differing only in case stop being distinct keys — the id tiebreaker is
    # what makes the order total, which LIMIT/OFFSET requires.
    query = apply_sort(query, sort).order_by(func.lower(Project.name), Project.id)
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total


async def get_project_view(
    db: AsyncSession, project_id: int, tenant_id: int
) -> ProjectView:
    row = (
        await db.execute(_view_query(tenant_id).where(Project.id == project_id))
    ).first()
    if row is None:
        # 404 rather than 403: a 403 confirms the row exists in another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return _to_view(row)


async def get_project(db: AsyncSession, project_id: int, tenant_id: int) -> Project:
    """The bare entity, for callers that do not need the labels."""
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def get_project_names(
    db: AsyncSession, project_ids, tenant_id: int
) -> dict[int, str]:
    """Names for a set of project ids, tenant-qualified.

    For OTHER entities that merely reference a project (booking_request,
    release) and want to render its name — never for validating that a
    caller-supplied id is usable, which stays `get_project`.

    Deliberately does NOT filter `deleted_at`: a soft-deleted project must
    still render its name on a live booking or release that references it —
    the row still carries that information, unlike `_agreement_query`, where
    a gone project makes the referencing row itself meaningless.
    """
    ids = {i for i in project_ids if i is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Project.id, Project.name).where(
                Project.id.in_(ids), Project.tenant_id == tenant_id
            )
        )
    ).all()
    return {pid: name for pid, name in rows}


async def _assert_team_is_ours(
    db: AsyncSession, tenant_id: int, team_group_id: Optional[int]
) -> None:
    """Validated against the ACTIVE tenant on create AND update.

    Under master-admin impersonation current_user.id and active_tenant_id
    belong to different tenants. This is also the IDOR class a 2026-07-16 audit
    found four instances of, and which the last two sub-projects' reviews found
    four more of — every time on a path nothing tested.
    """
    if team_group_id is None:
        return
    found = (
        await db.execute(
            select(UserGroup.id).where(
                UserGroup.id == team_group_id,
                UserGroup.tenant_id == tenant_id,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User group not found")


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(Project.id).where(
        Project.tenant_id == tenant_id,
        Project.deleted_at.is_(None),
        func.lower(Project.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(Project.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A project named '{name.strip()}' already exists in this tenant",
        )


async def create_project(
    db: AsyncSession, data: ProjectCreate, tenant_id: int
) -> ProjectView:
    await _assert_name_free(db, tenant_id, data.name)
    await _assert_team_is_ours(db, tenant_id, data.team_group_id)
    project = Project(
        tenant_id=tenant_id,
        name=data.name.strip(),
        code=data.code,
        description=data.description,
        team_group_id=data.team_group_id,
        is_active=data.is_active,
    )
    db.add(project)
    await db.flush()
    return await get_project_view(db, project.id, tenant_id)


async def update_project(
    db: AsyncSession, project_id: int, data: ProjectUpdate, tenant_id: int
) -> ProjectView:
    project = await get_project(db, project_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"].strip().lower() != project.name.lower():
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=project_id)
    if "team_group_id" in fields and fields["team_group_id"] != project.team_group_id:
        # Resubmitting the CURRENT value must not re-validate it — a group
        # can be soft-deleted after being assigned, and a PATCH editing some
        # unrelated field still round-trips the existing team_group_id. Same
        # exemption as the name check just above, and the same rule B1 gave
        # environment.operations_group_id: accept an archived group when it
        # equals the stored value, reject it as a new assignment.
        await _assert_team_is_ours(db, tenant_id, fields["team_group_id"])

    for key, value in fields.items():
        setattr(project, key, value.strip() if key == "name" else value)
    await db.flush()
    return await get_project_view(db, project_id, tenant_id)


async def delete_project(db: AsyncSession, project_id: int, tenant_id: int) -> None:
    """Soft delete, never refused. Cascades to the project's live usage
    agreements; leaves bookings and releases alone.

    Deliberately unlike user_group_service.delete_group, which 409s while any
    environment references it. A group operates a handful of environments; a
    project accumulates every booking and release it ever had, so a reference
    check would make every project permanently undeletable the moment someone
    booked against it.

    Bookings and releases are historical records of an event with a life of
    their own — they keep rendering the project's name after this, exactly as
    before. A usage agreement is different: it is a live statement of
    permission ("project P may use environment E"), not a record of something
    that happened, so it is meaningless once P is gone. Soft-delete it in the
    same transaction, or an environment owner is told forever that a defunct
    project uses their environment — see _agreement_query, whose join filters
    also make this true for rows that predate this cascade.

    `is_active` (unaffected here) is what removes a still-referenced project
    from pickers going forward.
    """
    project = await get_project(db, project_id, tenant_id)
    project.deleted_at = datetime.now(timezone.utc)
    await db.execute(
        update(UsageAgreement)
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.project_id == project_id,
            UsageAgreement.deleted_at.is_(None),
        )
        .values(deleted_at=project.deleted_at)
    )
    await db.flush()


def _agreement_query(tenant_id: int):
    """One select carrying both ends' names, tenant-qualified on each join.

    Both joins also require the counterparty to still be live. Unlike
    _view_query's UserGroup join — which deliberately keeps an archived
    team's name on a live project — an agreement whose project or
    environment is gone is meaningless and must be invisible from both
    directions, whether it got that way via delete_project's cascade or (for
    an environment, which nothing cascades onto) a row that predates it.
    """
    return (
        select(UsageAgreement, Project.name, Environment.name)
        .join(
            Project,
            and_(Project.id == UsageAgreement.project_id,
                 Project.tenant_id == tenant_id,
                 Project.deleted_at.is_(None)),
        )
        .join(
            Environment,
            and_(Environment.id == UsageAgreement.environment_id,
                 Environment.tenant_id == tenant_id,
                 Environment.deleted_at.is_(None)),
        )
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
        )
    )


async def list_agreements_for_project(
    db: AsyncSession, project_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    await get_project(db, project_id, tenant_id)  # 404s for another tenant's project
    query = (
        _agreement_query(tenant_id)
        .where(UsageAgreement.project_id == project_id)
        .order_by(func.lower(Environment.name), UsageAgreement.id)
    )
    return await fetch_page_rows(db, query, page)


async def list_agreements_for_environment(
    db: AsyncSession, environment_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    found = (
        await db.execute(
            select(Environment.id).where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    query = (
        _agreement_query(tenant_id)
        .where(UsageAgreement.environment_id == environment_id)
        .order_by(func.lower(Project.name), UsageAgreement.id)
    )
    return await fetch_page_rows(db, query, page)


async def create_agreement(
    db: AsyncSession, project_id: int, data: UsageAgreementCreate, tenant_id: int
):
    await get_project(db, project_id, tenant_id)

    if (
        data.starts_at is not None
        and data.ends_at is not None
        and data.ends_at < data.starts_at
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ends_at must not be earlier than starts_at",
        )

    env = (
        await db.execute(
            select(Environment.id).where(
                Environment.id == data.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Only an EXACT duplicate is refused. Overlapping windows are a statement
    # about intent, not a contradiction the system must resolve — deciding what
    # an overlap means is A3's job, once something reads them.
    duplicate = (
        await db.execute(
            select(UsageAgreement.id).where(
                UsageAgreement.tenant_id == tenant_id,
                UsageAgreement.project_id == project_id,
                UsageAgreement.environment_id == data.environment_id,
                UsageAgreement.starts_at.is_(data.starts_at)
                if data.starts_at is None
                else UsageAgreement.starts_at == data.starts_at,
                UsageAgreement.ends_at.is_(data.ends_at)
                if data.ends_at is None
                else UsageAgreement.ends_at == data.ends_at,
                UsageAgreement.deleted_at.is_(None),
            )
        )
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This project already has an agreement for that environment over "
            "exactly that window",
        )

    agreement = UsageAgreement(
        tenant_id=tenant_id,
        project_id=project_id,
        environment_id=data.environment_id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        notes=data.notes,
    )
    db.add(agreement)
    await db.flush()

    row = (
        await db.execute(
            _agreement_query(tenant_id).where(UsageAgreement.id == agreement.id)
        )
    ).first()
    return row


async def delete_agreement(
    db: AsyncSession, project_id: int, agreement_id: int, tenant_id: int
) -> None:
    await get_project(db, project_id, tenant_id)
    agreement = (
        await db.execute(
            select(UsageAgreement).where(
                UsageAgreement.id == agreement_id,
                UsageAgreement.project_id == project_id,
                UsageAgreement.tenant_id == tenant_id,
                UsageAgreement.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if agreement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usage agreement not found")
    # Soft, not hard: an agreement is a statement of intent with a history, and
    # A3 will want to know one was withdrawn rather than find it absent.
    agreement.deleted_at = datetime.now(timezone.utc)
    await db.flush()
