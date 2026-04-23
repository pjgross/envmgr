"""api_key_auth FastAPI dependency — 401/403 behaviour."""
import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import api_key_service


def _build_app(db_session):
    r = APIRouter()

    @r.get("/_probe")
    async def probe(key=Depends(api_key_auth(required_scope="webhooks:deployment"))):
        return {"tenant_id": key.tenant_id, "scopes": key.scopes}

    app = FastAPI()
    app.include_router(r)

    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_missing_header_401(db_session):
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_with_scope_200(db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe", headers={"X-Api-Key": raw})
        assert r.status_code == 200
        assert r.json()["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_wrong_scope_403(db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["other:scope"],
    )
    await db_session.commit()
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe", headers={"X-Api-Key": raw})
        assert r.status_code == 403
