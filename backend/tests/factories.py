"""Helpers that create real parent rows for foreign keys.

Why this exists: SQLite does not enforce foreign keys unless `PRAGMA
foreign_keys=ON` is set per connection, and it wasn't. So tests could insert a
Build with `subsystem_id=1`, or a Release with `raised_by=1`, without those rows
existing at all — and pass. Running the same suite against PostgreSQL surfaced
30 such tests immediately.

The pragma is on for SQLite now (see conftest), so both engines agree. These
helpers give tests a real parent to point at instead of a hopeful integer, and
each is idempotent per tenant so callers don't have to track what already exists.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.models.booking_lifecycle import BookingType
from app.db.models.build import Build
from app.db.models.change_request import ChangeRequest
from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import SubSystem, System
from app.db.models.user import User


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
    db: AsyncSession, tenant_id: int, username: str = "fk-parent-user"
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
        role="Admin",
    )
    db.add(user)
    await db.flush()
    return user


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


async def ensure_environment(db: AsyncSession, tenant_id: int, slot: int = 1) -> Environment:
    """A real environment for `tenant_id`, addressed by a small integer.

    Tests historically passed literal `environment_id=1` / `=2` to mean "two
    different environments". `slot` preserves that intent while pointing at rows
    that exist; it is idempotent, so repeated calls with the same slot return the
    same environment.
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
    environment = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id)
    db.add(environment)
    await db.flush()
    return environment


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
