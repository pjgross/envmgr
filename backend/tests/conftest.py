"""
Shared test fixtures.

Uses an in-memory SQLite database so no running PostgreSQL is required.
The app's get_db dependency is overridden to inject the test session.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base, get_db
from app.db.models.user import Tenant, User
from app.db.models.environment import Environment
from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType
from app.core.security import get_password_hash

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio event loop policy."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    """HTTP test client with the DB dependency overridden."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
    env = Environment(
        tenant_id=test_tenant.id,
        name="test-env",
        environment_type="dev",
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture(scope="function")
async def test_booking_type(db_session, test_tenant) -> BookingType:
    """A booking type backed by a lifecycle template with a 'draft' initial state."""
    tpl = BookingLifecycleTemplate(
        tenant_id=test_tenant.id,
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
