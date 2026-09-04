"""Helpers that create real parent rows for foreign keys.

Why this exists: SQLite does not enforce foreign keys unless `PRAGMA
foreign_keys=ON` is set per connection, and it wasn't. So tests could insert a
Build with `subsystem_id=1`, or a Release with `raised_by=1`, without those rows
existing at all — and pass. Running the same suite against PostgreSQL surfaced
30 such tests immediately.

The pragma is on for SQLite now (see conftest), so both engines agree. These
helpers give tests a real parent to point at instead of a hopeful integer.

NAMING: `ensure_*` is idempotent per (tenant, name) — call it as often as you
like and you get the same row back, so callers don't have to track what already
exists. `make_*` ALWAYS creates a new row, because the thing it builds has no
natural per-tenant identity to be idempotent about (a tenant may hold any number
of bookings for one environment). Check the prefix before assuming.

The one exception is `ensure_build`, which predates this convention and always
creates a row despite its name — its own docstring says so, and it has call
sites in seven modules, so it keeps the name until something else takes it.
`ensure_deployment` is a second: a deployment has no per-tenant identity to be
idempotent about (an environment may be deployed to any number of times), so
it too always creates a new row — its own docstring says so as well.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.build import Build
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.environment_decommission import EnvironmentDecommission
from app.db.models.environment_group import EnvironmentGroup
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.pir import PIR
from app.db.models.pir_finding import PirAction, PirFinding
from app.db.models.project import Project
from app.db.models.release import Release
from app.db.models.system import SubSystem, System
from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember


async def ensure_subsystem(
    db: AsyncSession, tenant_id: int, name: str = "test-subsystem"
) -> SubSystem:
    """A subsystem (with its required parent system) for `tenant_id`."""
    existing = (
        await db.execute(
            select(SubSystem).where(
                SubSystem.tenant_id == tenant_id, SubSystem.name == name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    system = System(tenant_id=tenant_id, name=f"{name}-system")
    db.add(system)
    await db.flush()

    subsystem = SubSystem(
        tenant_id=tenant_id,
        name=name,
        system_id=system.id,
        component_type="web_service",
    )
    db.add(subsystem)
    await db.flush()
    return subsystem


async def ensure_booking_type(
    db: AsyncSession, tenant_id: int, name: str = "test-booking-type"
) -> BookingType:
    """A booking type, plus the lifecycle template it requires."""
    existing = (
        await db.execute(
            select(BookingType).where(
                BookingType.tenant_id == tenant_id, BookingType.name == name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="booking",
        name=f"{name}-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "confirmed", "label": "Confirmed", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db.add(template)
    await db.flush()

    booking_type = BookingType(
        tenant_id=tenant_id, name=name, lifecycle_template_id=template.id
    )
    db.add(booking_type)
    await db.flush()
    return booking_type


async def ensure_user(
    db: AsyncSession, tenant_id: int, username: str = "fk-parent-user",
    role: str = "Admin",
) -> User:
    """A user for `tenant_id`, for columns like release.raised_by."""
    existing = (
        await db.execute(
            select(User).where(User.tenant_id == tenant_id, User.username == username)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        tenant_id=tenant_id,
        username=username,
        email=f"{username}@test.local",
        password_hash=get_password_hash("password123"),
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def ensure_user_group(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-group"
) -> UserGroup:
    """A real group for `tenant_id`. Idempotent per (tenant, name).

    `environment.operations_group_id` and `user_group_member.group_id` are both
    real FKs, so tests must never pass a bare `1`.
    """
    existing = (
        await db.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.name == name,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    group = UserGroup(tenant_id=tenant_id, name=name)
    db.add(group)
    await db.flush()
    return group


async def ensure_project(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-project"
) -> Project:
    """A project for `tenant_id`. Idempotent per (tenant, name).

    `booking_request.project_id`, `release.owning_project_id` and
    `usage_agreement.project_id` are all real FKs, so tests must never pass a
    bare `1`.
    """
    existing = (
        await db.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.name == name,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    project = Project(tenant_id=tenant_id, name=name)
    db.add(project)
    await db.flush()
    return project


async def ensure_environment_tier(
    db: AsyncSession, tenant_id: int, name: str = "SIT"
) -> EnvironmentTier:
    """A real tier for `tenant_id`. Idempotent per (tenant, name).

    Environment.tier_id is NOT NULL, so every test that builds an environment
    needs one of these.
    """
    existing = (
        await db.execute(
            select(EnvironmentTier).where(
                EnvironmentTier.tenant_id == tenant_id, EnvironmentTier.name == name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    tier = EnvironmentTier(tenant_id=tenant_id, name=name, category=name.lower())
    db.add(tier)
    await db.flush()
    return tier


async def ensure_environment(
    db: AsyncSession, tenant_id: int, slot: int = 1,
    *, operations_group_id: Optional[int] = None,
) -> Environment:
    """A real environment for `tenant_id`, addressed by a small integer.

    Tests historically passed literal `environment_id=1` / `=2` to mean "two
    different environments". `slot` preserves that intent while pointing at rows
    that exist; it is idempotent, so repeated calls with the same slot return the
    same environment. Callers building several distinct environments in one
    test (e.g. one per operations group) must pass distinct `slot` values —
    idempotency is keyed on (tenant, slot), and `operations_group_id` is only
    applied on the row this call CREATES, never retro-fitted onto an existing
    one it merely returns.
    """
    name = f"test-env-{slot}"
    existing = (
        await db.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id, Environment.name == name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    tier = await ensure_environment_tier(db, tenant_id)
    environment = Environment(
        tenant_id=tenant_id, name=name, tier_id=tier.id,
        operations_group_id=operations_group_id,
    )
    db.add(environment)
    await db.flush()
    return environment


async def make_booking(
    db: AsyncSession,
    tenant_id: int,
    *,
    booked_by: int,
    environment: Environment,
    project_id: int | None = None,
    booking_type: BookingType | None = None,
    start: datetime = datetime(2026, 3, 1, tzinfo=timezone.utc),
    end: datetime = datetime(2026, 3, 5, tzinfo=timezone.utc),
) -> Booking:
    """A booking, plus the BookingRequest that carries its project link.

    `make_`, not `ensure_`: ALWAYS A NEW ROW. A tenant may hold any number of
    bookings for one environment, so there is nothing to be idempotent about, and
    tests that want two distinct bookings must get two. It was called
    `ensure_booking` until a reviewer pointed out that a name promising
    idempotence on a helper that has none is the kind of thing a future test
    author reads once and trusts.

    The SHARED booking builder — `test_agreement_gap.py`'s `_booking` is a thin
    adapter onto this, because two builders drifting apart is how a test ends up
    asserting against a row shape the code under test never sees. It is NOT the
    only one in the suite: `test_conflict_service.py` has its own `_make_booking`
    and ~15 modules construct `Booking(` directly. Before consolidating any of
    them onto this helper, check `status` — this builder takes none, so a suite
    that depends on `submitted` would silently flip to the model default.

    Pass `booking_type` when the caller already has one (a fixture, or another
    tenant's); otherwise the idempotent per-tenant default is used.

    `booking_request.project_id` is what A3's gap predicate reads; the booking
    itself has no project column. `project_name` is the free text the UI labels
    "Purpose" and is deliberately unrelated to it (A1).
    """
    if booking_type is None:
        booking_type = await ensure_booking_type(db, tenant_id)
    request = BookingRequest(
        tenant_id=tenant_id,
        project_name="a purpose, not a project",
        project_id=project_id,
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=booked_by,
    )
    db.add(request)
    await db.flush()

    booking = Booking(
        tenant_id=tenant_id,
        environment_id=environment.id,
        start_date=start,
        end_date=end,
        booking_request_id=request.id,
    )
    db.add(booking)
    await db.flush()
    return booking


async def ensure_environment_group(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-env-group"
) -> EnvironmentGroup:
    """An environment group for `tenant_id`. Idempotent per (tenant, name).

    `booking.environment_group_id` and `environment_group_member.group_id` are
    both real FKs now, so tests must never pass a bare `1`.
    """
    existing = (
        await db.execute(
            select(EnvironmentGroup).where(
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.name == name,
                EnvironmentGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    group = EnvironmentGroup(tenant_id=tenant_id, name=name)
    db.add(group)
    await db.flush()
    return group


async def ensure_environment_request(
    db: AsyncSession, tenant_id: int, **overrides
) -> EnvironmentRequest:
    """A request for `tenant_id`, defaulting to a valid access request.

    `lifecycle_id`, `requested_by` and `environment_id` are all real FKs, so a
    test must never pass a bare `1`. Pass overrides to change kind or targets.
    """
    from app.db.models.lifecycle import LifecycleTemplate

    user = await ensure_user(db, tenant_id)
    env = await ensure_environment(db, tenant_id)

    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == "environment_request",
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if tpl is None:
        tpl = LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type="environment_request",
            name="fk-parent-request-lifecycle",
            definition={
                "states": [
                    {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                ],
                "transitions": [],
                "field_permissions": {},
            },
        )
        db.add(tpl)
        await db.flush()

    fields = {
        "tenant_id": tenant_id,
        "kind": "access",
        "status": "draft",
        "lifecycle_id": tpl.id,
        "requested_by": user.id,
        "justification": "fk-parent justification",
        "environment_id": env.id,
    }
    fields.update(overrides)
    req = EnvironmentRequest(**fields)
    db.add(req)
    await db.flush()
    return req


async def post_environment(client, headers: dict, name: str, **extra):
    """POST /environments with the tier, owner and expiry it now requires.

    Returns the raw response, so a caller can still assert on the status code.
    Everything is resolved over HTTP, so a test needs no database fixtures to
    use it — `extra` overrides or adds to the body.
    """
    listed = await client.get("/api/v1/environment-tiers/", headers=headers)
    match = [t for t in listed.json() if t["name"] == "SIT"]
    if match:
        tier_id = match[0]["id"]
    else:
        created = await client.post(
            "/api/v1/environment-tiers/", headers=headers, json={"name": "SIT"}
        )
        tier_id = created.json()["id"]

    me = await client.get("/api/v1/auth/me", headers=headers)
    body = {
        "name": name,
        "tier_id": tier_id,
        "owner_user_id": me.json()["id"],
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=365)
        ).isoformat(),
    }
    body.update(extra)
    return await client.post("/api/v1/environments/", headers=headers, json=body)


_build_seq = 0


async def ensure_build(db: AsyncSession, tenant_id: int) -> Build:
    """A build (with its subsystem) for `tenant_id`.

    Always a new row — Build has a UNIQUE(tenant_id, subsystem_id, git_sha,
    build_number), so callers that want several must get distinct ones.
    """
    global _build_seq
    _build_seq += 1
    subsystem = await ensure_subsystem(db, tenant_id)
    build = Build(
        tenant_id=tenant_id,
        subsystem_id=subsystem.id,
        git_sha=f"{_build_seq:040d}",
        build_number=f"fk-{_build_seq}",
        commit_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(build)
    await db.flush()
    return build


async def ensure_change_request(
    db: AsyncSession, tenant_id: int, title: str = "fk-parent-cr"
) -> ChangeRequest:
    """A change request for `tenant_id`.

    `deployment.change_request_id` is NOT NULL with ondelete=RESTRICT, so every
    deployment needs one — tests used to pass a bare `1`.
    """
    existing = (
        await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.tenant_id == tenant_id, ChangeRequest.title == title
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="change_request",
        name=f"{title}-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db.add(template)
    await db.flush()

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    change_request = ChangeRequest(
        tenant_id=tenant_id,
        title=title,
        change_type="standard",
        status="draft",
        lifecycle_id=template.id,
        raised_by=(await ensure_user(db, tenant_id)).id,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=1),
    )
    db.add(change_request)
    await db.flush()
    return change_request


async def ensure_deployment(
    db: AsyncSession,
    tenant_id: int,
    environment_id: int,
    *,
    deployed_at: datetime,
    status: str = "success",
) -> Deployment:
    """A deployment against `environment_id`, for `tenant_id`.

    Named `ensure_*` for call-site consistency with its neighbours, but ALWAYS
    a new row — like `ensure_build`, which it uses. A deployment has no
    natural per-tenant identity to be idempotent about: an environment may be
    deployed to any number of times, and `deployment.event_id` is a fresh
    UUID on every call, so two calls never collide on
    `uq_deployment_tenant_event`.

    `build_id` and `change_request_id` are both real, NOT NULL FKs
    (`ondelete=RESTRICT`) — resolved via `ensure_build`/`ensure_change_request`
    rather than a fabricated id, per this module's whole reason for existing.
    """
    build = await ensure_build(db, tenant_id)
    change_request = await ensure_change_request(db, tenant_id)
    deployment = Deployment(
        tenant_id=tenant_id,
        build_id=build.id,
        environment_id=environment_id,
        change_request_id=change_request.id,
        event_id=str(uuid4()),
        deployed_at=deployed_at,
        status=status,
    )
    db.add(deployment)
    await db.flush()
    return deployment


async def add_group_member(
    db: AsyncSession, group: UserGroup, user: User
) -> UserGroupMember:
    """One `UserGroupMember` row, carrying the GROUP's `tenant_id` — the same
    denormalisation `UserGroupMember` itself documents (derivable through
    `group_id`, stored anyway so every tenant-scoped query on this table can
    filter `tenant_id` directly, without a join).

    `make_`, not `ensure_`: membership has no natural per-(group, user)
    identity to be idempotent about beyond the model's own unique constraint
    (`uq_user_group_member`), and repeating a membership a test already made
    should be a constraint violation, not a silent no-op.
    """
    member = UserGroupMember(
        tenant_id=group.tenant_id, group_id=group.id, user_id=user.id
    )
    db.add(member)
    await db.flush()
    return member


async def make_decommission(
    db: AsyncSession,
    tenant_id: int,
    *,
    environment_id: int,
    initiated_by: Optional[int] = None,
    reason: str = "test decommission",
    warned_at: Optional[datetime] = None,
    scheduled_teardown_at: Optional[datetime] = None,
) -> EnvironmentDecommission:
    """A decommission record against `environment_id`, for `tenant_id`.

    `make_`, not `ensure_`: a tenant may raise any number of decommission
    attempts against the same environment over its history (cancelled, then
    raised again), so there is nothing to be idempotent about.

    `initiated_by` is a real, NOT NULL FK to `user`. When the caller has no
    particular initiator in mind, one is created via `ensure_user` rather than
    pointing the row at an id nobody created — this module's whole reason for
    existing.
    """
    if initiated_by is None:
        initiator = await ensure_user(db, tenant_id)
        initiated_by = initiator.id
    if warned_at is None:
        warned_at = datetime.now(timezone.utc)
    if scheduled_teardown_at is None:
        scheduled_teardown_at = warned_at + timedelta(days=5)

    decommission = EnvironmentDecommission(
        tenant_id=tenant_id,
        environment_id=environment_id,
        reason=reason,
        warned_at=warned_at,
        scheduled_teardown_at=scheduled_teardown_at,
        initiated_by=initiated_by,
    )
    db.add(decommission)
    await db.flush()
    return decommission


async def make_incident(
    db: AsyncSession,
    tenant_id: int,
    *,
    title: str = "test incident",
    status: str = "open",
    severity: str = "P2",
    detected_at: Optional[datetime] = None,
) -> Incident:
    """An incident for `tenant_id`.

    `make_`, not `ensure_`: a tenant may raise any number of incidents over its
    history, so there is nothing to be idempotent about.
    """
    if detected_at is None:
        detected_at = datetime.now(timezone.utc)
    incident = Incident(
        tenant_id=tenant_id,
        title=title,
        status=status,
        severity=severity,
        detected_at=detected_at,
    )
    db.add(incident)
    await db.flush()
    return incident


async def make_pir_action(
    db: AsyncSession,
    tenant_id: int,
    *,
    title: str = "test pir action",
    owner_id: Optional[int] = None,
    status: str = "open",
    due_date: Optional[datetime] = None,
    finding_id: Optional[int] = None,
    finding_kind: str = "went_wrong",
    release_name: str = "fk-parent-release",
) -> PirAction:
    """A `PirAction` for `tenant_id`, building the whole chain it hangs off
    (release -> lifecycle template -> PIR -> finding) when `finding_id` is not
    given.

    `make_`, not `ensure_`: a finding may carry any number of actions, so
    there is nothing to be idempotent about.
    """
    if finding_id is None:
        raiser = await ensure_user(db, tenant_id)
        tpl = LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type="release",
            name=f"fk-parent-release-lifecycle-{uuid4().hex[:8]}",
            is_default=False,
            definition={
                "states": [
                    {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                ],
                "transitions": [],
                "field_permissions": {},
            },
        )
        db.add(tpl)
        await db.flush()

        release = Release(
            tenant_id=tenant_id,
            name=release_name,
            release_type="Major",
            release_kind="project",
            lifecycle_template_id=tpl.id,
            status="draft",
            raised_by=raiser.id,
        )
        db.add(release)
        await db.flush()

        pir = PIR(
            tenant_id=tenant_id, release_id=release.id, status="draft",
            created_by=raiser.id,
        )
        db.add(pir)
        await db.flush()

        finding = PirFinding(
            tenant_id=tenant_id, pir_id=pir.id, kind=finding_kind, seq=1,
            title=f"finding for {title}",
        )
        db.add(finding)
        await db.flush()
        finding_id = finding.id

    action = PirAction(
        tenant_id=tenant_id,
        finding_id=finding_id,
        seq=1,
        title=title,
        owner_id=owner_id,
        due_date=due_date,
        status=status,
    )
    db.add(action)
    await db.flush()
    return action
