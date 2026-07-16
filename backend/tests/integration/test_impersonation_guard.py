"""Impersonation is only honoured while the bearer is still a master admin.

Guards the demoted-admin / stale-token case in get_current_user: a signed
impersonation claim must NOT grant cross-tenant access after the privilege is
revoked (the token stays valid until expiry).
"""
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.security import create_access_token, get_current_user, get_password_hash
from app.db.models.user import Tenant, User


@pytest.mark.asyncio
async def test_impersonation_ignored_after_master_admin_revoked(db_session):
    home = Tenant(name="Home Org", slug="home-imp")
    target = Tenant(name="Target Org", slug="target-imp")
    db_session.add_all([home, target])
    await db_session.flush()
    admin = User(
        tenant_id=home.id, username="mimp", email="m@imp.com",
        password_hash=get_password_hash("x"), role="Admin", is_active=True,
        is_master_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    token = create_access_token({
        "sub": str(admin.id), "tenant_id": home.id,
        "impersonating_tenant_id": target.id,
    })
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # While still a master admin: impersonation is honoured.
    u = await get_current_user(credentials=creds, db=db_session)
    assert u.active_tenant_id == target.id

    # Revoke master admin; the SAME token now falls back to the home tenant.
    admin.is_master_admin = False
    await db_session.commit()
    u2 = await get_current_user(credentials=creds, db=db_session)
    assert u2.active_tenant_id == home.id
