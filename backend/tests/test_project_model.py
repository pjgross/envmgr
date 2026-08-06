"""The project entity, its agreement table, and the two links A1 adds."""
import pytest
from sqlalchemy import select

from app.db.models.project import Project, UsageAgreement
from tests.factories import (
    ensure_environment, ensure_project, ensure_user_group,
)


@pytest.mark.asyncio
async def test_project_persists_with_its_tenant(db_session, test_tenant):
    project = Project(tenant_id=test_tenant.id, name="Mortgage Replatform")
    db_session.add(project)
    await db_session.flush()

    assert project.id is not None
    assert project.is_active is True
    assert project.deleted_at is None
    assert project.code is None
    # A project need not have a team — one can be assigned later.
    assert project.team_group_id is None


@pytest.mark.asyncio
async def test_a_projects_team_is_a_user_group(db_session, test_tenant):
    """No project_member table: B3a's UserGroup is deliberately generic so a
    person's group memberships answer both 'which environments do you operate'
    and 'which projects are you on'."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Mortgage Team")
    project = await ensure_project(db_session, test_tenant.id)
    project.team_group_id = group.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(Project.team_group_id).where(Project.id == project.id)
    )).scalar_one()
    assert stored == group.id


@pytest.mark.asyncio
async def test_usage_agreement_links_a_project_to_an_environment(
    db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)

    agreement = UsageAgreement(
        tenant_id=test_tenant.id, project_id=project.id, environment_id=env.id
    )
    db_session.add(agreement)
    await db_session.flush()

    assert agreement.id is not None
    # The window is optional: "this project uses this environment" is a
    # legitimate statement without dates.
    assert agreement.starts_at is None
    assert agreement.ends_at is None


@pytest.mark.asyncio
async def test_one_environment_can_serve_several_projects(db_session, test_tenant):
    """Shared estates are the normal case — this is why the link is a junction
    and not an owning FK on environment."""
    env = await ensure_environment(db_session, test_tenant.id)
    a = await ensure_project(db_session, test_tenant.id, name="Project A")
    b = await ensure_project(db_session, test_tenant.id, name="Project B")

    for project in (a, b):
        db_session.add(UsageAgreement(
            tenant_id=test_tenant.id, project_id=project.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(UsageAgreement.project_id).where(
            UsageAgreement.environment_id == env.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([a.id, b.id])


@pytest.mark.asyncio
async def test_booking_request_keeps_its_free_text_alongside_the_link(
    db_session, test_tenant, test_booking_type, test_user
):
    """project_name is NOT migrated or removed. In real data it holds a booking
    label — 'Health Demo Booking', 'Reserved check' — so promoting it would
    manufacture junk projects. project_id arrives beside it, nullable."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking_request import BookingRequest

    project = await ensure_project(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Health Demo Booking",   # still free text, still required
        project_id=project.id,                 # the new link
        booking_type_id=test_booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    assert req.project_name == "Health Demo Booking"
    assert req.project_id == project.id


@pytest.mark.asyncio
async def test_release_link_is_named_to_avoid_the_release_kind_collision(
    db_session, tenant, user, release_lifecycle_template
):
    """`release_kind='project'` already lives in this table meaning 'not an
    enterprise release'. Two things called project on one row is how a future
    reader gets it wrong, so the FK is owning_project_id."""
    from app.db.models.release import Release

    project = await ensure_project(db_session, tenant.id)
    release = Release(
        tenant_id=tenant.id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=release_lifecycle_template.id,
        status="draft", raised_by=user.id, owning_project_id=project.id,
    )
    db_session.add(release)
    await db_session.flush()

    assert release.owning_project_id == project.id
    assert release.release_kind == "project"  # unrelated, and untouched
