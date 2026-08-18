"""
Shared test fixtures.

Defaults to in-memory SQLite so no running database is required. Set
TEST_DATABASE_URL to a PostgreSQL DSN to run the same suite against the engine
production actually uses:

    TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
        uv run pytest -q

That matters because several migrations and constraints are dialect-gated — the
partial unique indexes guarded by `if dialect.name != "postgresql": return` are
inert under SQLite, so a SQLite-only run cannot exercise them. CI runs both.
NOTE: neither leg actually exercises those partial indexes even on
PostgreSQL — both `db_engine` fixtures below build schema with
`Base.metadata.create_all`, never `alembic upgrade head`, and the indexes
are declared only in migration DDL, not on any model's `__table_args__`.
Running against a real PostgreSQL catches ordinary collation/dialect
differences, not those migration-only constraints; see
test_migration_schema_drift.py and environment_request_service's
_fulfil_new_environment docstring for the app-level guard this gap forced.

The app's get_db dependency is overridden to inject the test session.
"""
import os

# Settings rejects the repo's sentinel SECRET_KEY outside DEBUG, and app.main
# builds Settings at import time — so this must precede any app import.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-deployment")

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine as sync_create_engine, event, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.main import app
from app.db.base import Base, get_db
from app.db.models.user import Tenant, User
from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.booking_lifecycle import BookingType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_request import BookingRequest
from app.db.models.booking import Booking
from app.db.models.system import System
from app.core.security import get_password_hash
from app.services.environment_request_defaults import (
    seed_environment_request_defaults_for_tenant,
)
from datetime import datetime, timezone, timedelta

# `or` not a get() default: an empty value (e.g. a CI matrix leg that sets the
# variable to "") must fall back too, not be passed to SQLAlchemy as a URL.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite+aiosqlite:///:memory:"
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")


if IS_POSTGRES:
    # Schema setup and inter-test cleanup go through a *sync* (psycopg2) engine.
    # An asyncpg connection is bound to the event loop that opened it, and
    # pytest-asyncio gives each test its own loop — so a session-scoped async
    # engine blows up with "attached to a different loop" on the second test.
    # A sync engine has no such affinity, and it keeps the expensive part
    # (building 50-odd tables) out of every test.
    SYNC_TEST_DATABASE_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")

    @pytest.fixture(scope="session")
    def _pg_sync_engine():
        engine = sync_create_engine(SYNC_TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()

    @pytest.fixture(scope="function")
    def _pg_clean(_pg_sync_engine):
        """Start every test from an empty database.

        RESTART IDENTITY keeps parity with the SQLite path, where each test got a
        virgin database and therefore ids from 1 — some tests rely on that.
        CASCADE is required by the FK graph.
        """
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        with _pg_sync_engine.connect() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    @pytest_asyncio.fixture(scope="function")
    async def db_engine(_pg_clean):
        # NullPool: don't hand a pooled connection to the next test's loop.
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        yield engine
        await engine.dispose()

else:

    def _enforce_foreign_keys(dbapi_connection, _record):
        """SQLite ignores foreign keys unless asked, per connection.

        Without this a test can insert a Build pointing at a subsystem that does
        not exist and still pass — which is what 30 tests were doing until the
        suite was first pointed at PostgreSQL. Both engines now enforce the same
        constraints.

        Registered on this engine only, never globally on Engine: other tests
        (tests/test_migration_schema_drift.py) build psycopg2 engines in the same
        process, and PRAGMA is not valid SQL there.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @pytest_asyncio.fixture(scope="function")
    async def db_engine():
        """Create a fresh in-memory SQLite engine for each test."""
        engine = create_async_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(engine.sync_engine, "connect", _enforce_foreign_keys)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """Provide an async database session backed by the test engine."""
    TestSessionLocal = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """HTTP test client with the DB dependency overridden.

    Note this override does NOT reproduce get_db()'s commit-on-success /
    rollback-on-exception behaviour: the session is shared with the test body, and
    rolling back per request would discard fixture rows. Transaction-boundary
    behaviour therefore has to be asserted at the service level — see
    test_auth_session_service.test_reuse_raises_the_variant_that_demands_a_commit.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def realistic_client(db_engine):
    """An HTTP test client whose get_db override mirrors production: commit on
    success, rollback on exception. Each request gets its own session, backed
    by the same engine as the rest of the test's fixtures.

    Use this — not `client` — whenever the behaviour under test depends on a
    write surviving (or not surviving) a request that raises. `client` shares
    one session with the test body and never rolls back, so it cannot catch a
    write that only get_db's real rollback would discard.

    `client` and `realistic_client` both assign into the same global
    `app.dependency_overrides[get_db]`, and neither depends on the other, so
    a test that requests both fixtures by name gets `client`'s override
    silently — not a mix of the two, and not necessarily this fixture's
    commit/rollback semantics even though it was asked for.
    """
    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def test_tenant(db_session) -> Tenant:
    """A persisted test tenant."""
    tenant = Tenant(name="Test Org", slug="test-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session, test_tenant) -> User:
    """An active admin user belonging to test_tenant."""
    user = User(
        tenant_id=test_tenant.id,
        username="testadmin",
        email="admin@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def test_environment(db_session, test_tenant) -> Environment:
    """A persisted environment in test_tenant."""
    tier = EnvironmentTier(tenant_id=test_tenant.id, name="Dev", category="dev")
    db_session.add(tier)
    await db_session.flush()
    env = Environment(
        tenant_id=test_tenant.id,
        name="test-env",
        tier_id=tier.id,
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture(scope="function")
async def test_booking_type(db_session, test_tenant) -> BookingType:
    """A booking type backed by a lifecycle template with a 'draft' initial state."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="booking",
        name="default",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(
        tenant_id=test_tenant.id,
        name="Standard",
        lifecycle_template_id=tpl.id,
    )
    db_session.add(bt)
    await db_session.commit()
    await db_session.refresh(bt)
    return bt


@pytest_asyncio.fixture(scope="function")
async def second_tenant_factory(db_session):
    """Yields an async factory that creates a second tenant with its own admin."""
    async def _factory(name: str = "Second Org", slug: str = "second-org"):
        t = Tenant(name=name, slug=slug)
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)
        u = User(
            tenant_id=t.id,
            username=f"{slug}-admin",
            email=f"admin@{slug}.com",
            password_hash=get_password_hash("password123"),
            role="Admin",
            is_active=True,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        return t, u
    return _factory


@pytest_asyncio.fixture(scope="function")
async def auth_headers(client, test_tenant, test_user) -> dict:
    """Bearer token headers for test_user."""
    response = await client.post("/api/v1/auth/login", json={
        "username": test_user.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def member_headers(client, db_session, test_tenant) -> dict:
    """Bearer token headers for a non-Admin (Developer) user in test_tenant —
    the "any tenant member" half of a reads-open/writes-Admin split, following
    how auth_headers is built. No equivalent shared fixture existed; several
    test files define a similarly-shaped local `developer_headers` instead."""
    user = User(
        tenant_id=test_tenant.id,
        username="testmember",
        email="member@test.com",
        password_hash=get_password_hash("password123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/api/v1/auth/login", json={
        "username": user.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def test_booking(db_session, test_tenant, test_environment, test_user, test_booking_type):
    """A persisted booking request with a single child booking."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1)
    end = start + timedelta(days=2)

    # Create booking request
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Test Project",
        booking_type_id=test_booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    # Create booking linked to request
    booking = Booking(
        tenant_id=test_tenant.id,
        environment_id=test_environment.id,
        start_date=start,
        end_date=end,
        booking_request_id=req.id,
    )
    db_session.add(booking)
    await db_session.commit()
    await db_session.refresh(booking)
    return booking


@pytest_asyncio.fixture(scope="function")
async def test_conflicting_booking(db_session, test_tenant, test_environment, test_user, test_booking_type):
    """A persisted booking request with a single child booking that overlaps with test_booking."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1, hours=12)  # overlaps with test_booking
    end = start + timedelta(days=1)

    # Create booking request
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Conflicting Project",
        booking_type_id=test_booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    # Create booking linked to request
    booking = Booking(
        tenant_id=test_tenant.id,
        environment_id=test_environment.id,
        start_date=start,
        end_date=end,
        booking_request_id=req.id,
    )
    db_session.add(booking)
    await db_session.commit()
    await db_session.refresh(booking)
    return booking


# ---------------------------------------------------------------------------
# Phase 3 short-name aliases and new fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def tenant(db_session) -> Tenant:
    """Short-name alias for test_tenant; used by Phase 3 model tests."""
    t = Tenant(name="Phase3 Org", slug="phase3-org")
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest_asyncio.fixture(scope="function")
async def user(db_session, tenant) -> User:
    """Short-name alias for a test user in the `tenant` fixture."""
    u = User(
        tenant_id=tenant.id,
        username="p3admin",
        email="p3admin@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture(scope="function")
async def system(db_session, tenant) -> System:
    """A persisted System row for the `tenant` fixture; used by Phase 3 tests."""
    s = System(
        tenant_id=tenant.id,
        name="Core Platform",
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest_asyncio.fixture(scope="function")
async def release_lifecycle_template(db_session, tenant) -> LifecycleTemplate:
    """A LifecycleTemplate with entity_type='release'; shared by Phase 3 model tests."""
    template = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Test Major",
        description="",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]},
                {"from_state": "submitted", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
                "submitted": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template


@pytest_asyncio.fixture(scope="function")
async def environment_request_lifecycle(db_session, test_tenant) -> None:
    """Seeds the environment_request lifecycle template for `test_tenant`.

    `test_tenant` builds a bare Tenant row directly, bypassing
    tenant_service.create_tenant — the only place that calls this seeder — so
    any test that creates an environment request needs it seeded by hand.
    Explicit rather than autouse (unlike the B3b module fixture this replaces)
    so a test that wants a different template can simply not request it,
    matching test_booking_type / test_change_requests.py's test_cr_lifecycle.
    """
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
