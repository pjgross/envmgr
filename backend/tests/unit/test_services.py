"""Unit tests for tenant_service and user_admin_service — no database required."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.services.tenant_service import (
    list_tenants,
    get_tenant,
    create_tenant,
    update_tenant,
    disable_tenant,
)
from app.services.user_admin_service import (
    list_users,
    get_user,
    create_user_in_tenant,
    update_user,
    set_user_role,
    deactivate_user,
)
from app.api.v1.schemas import TenantCreate, TenantUpdate, UserAdminCreate, UserAdminUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(scalar_result=None, scalars_result=None):
    """Return a mock AsyncSession pre-configured with execute() returning the
    given values.  scalar_result is used for scalar_one_or_none();
    scalars_result is a list used for scalars().all()."""
    db = AsyncMock()

    execute_result = MagicMock()
    if scalars_result is not None:
        execute_result.scalars.return_value.all.return_value = scalars_result
    if scalar_result is not None:
        execute_result.scalar_one_or_none.return_value = scalar_result
    else:
        execute_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=execute_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# tenant_service tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tenants_returns_results():
    tenant_a = MagicMock()
    tenant_b = MagicMock()
    db = _make_db(scalars_result=[tenant_a, tenant_b])

    result = await list_tenants(db)

    db.execute.assert_awaited_once()
    assert result == [tenant_a, tenant_b]


@pytest.mark.asyncio
async def test_get_tenant_raises_404_when_not_found():
    db = _make_db(scalar_result=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant(db, tenant_id=999)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Tenant not found"


@pytest.mark.asyncio
async def test_get_tenant_returns_tenant_when_found():
    mock_tenant = MagicMock()
    db = _make_db(scalar_result=mock_tenant)

    result = await get_tenant(db, tenant_id=1)

    assert result is mock_tenant


@pytest.mark.asyncio
async def test_create_tenant_calls_db_add_and_commit():
    # Slug uniqueness check returns None (no existing tenant)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = TenantCreate(name="ACME", slug="acme")
    await create_tenant(db, data)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_tenant_uses_correct_fields():
    created_tenant = None

    async def capture_refresh(obj):
        nonlocal created_tenant
        created_tenant = obj

    # Slug uniqueness check returns None (no existing tenant)
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=capture_refresh)

    data = TenantCreate(name="Beta Corp", slug="beta-corp", settings={"key": "value"})
    await create_tenant(db, data)

    added = db.add.call_args[0][0]
    assert added.name == "Beta Corp"
    assert added.slug == "beta-corp"
    assert added.settings == {"key": "value"}


@pytest.mark.asyncio
async def test_update_tenant_patches_fields():
    mock_tenant = MagicMock()
    mock_tenant.name = "Old Name"
    mock_tenant.slug = "old-slug"
    mock_tenant.settings = None

    db = _make_db(scalar_result=mock_tenant)

    data = TenantUpdate(name="New Name", slug="new-slug")
    await update_tenant(db, tenant_id=1, data=data)

    assert mock_tenant.name == "New Name"
    assert mock_tenant.slug == "new-slug"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_disable_tenant_sets_is_active_false():
    mock_tenant = MagicMock()
    mock_tenant.is_active = True
    db = _make_db(scalar_result=mock_tenant)

    await disable_tenant(db, tenant_id=1)

    assert mock_tenant.is_active is False
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# user_admin_service tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_filters_by_tenant_id():
    user_a = MagicMock()
    user_b = MagicMock()
    db = _make_db(scalars_result=[user_a, user_b])

    result = await list_users(db, tenant_id=42)

    db.execute.assert_awaited_once()
    assert result == [user_a, user_b]


@pytest.mark.asyncio
async def test_get_user_raises_404_when_not_found():
    db = _make_db(scalar_result=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_user(db, user_id=99, tenant_id=1)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


@pytest.mark.asyncio
async def test_get_user_returns_user_when_found():
    mock_user = MagicMock()
    db = _make_db(scalar_result=mock_user)

    result = await get_user(db, user_id=1, tenant_id=1)

    assert result is mock_user


@pytest.mark.asyncio
async def test_set_user_role_raises_400_for_invalid_role():
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await set_user_role(db, user_id=1, tenant_id=1, role="SuperAdmin")
    assert exc_info.value.status_code == 400
    assert "Invalid role" in exc_info.value.detail


@pytest.mark.asyncio
async def test_set_user_role_accepts_valid_roles():
    from app.core.security import Role
    valid_roles = [Role.ADMIN, Role.RELEASE_MANAGER, Role.TEST_MANAGER, Role.DEVELOPER, Role.VIEWER]

    for role in valid_roles:
        mock_user = MagicMock()
        db = _make_db(scalar_result=mock_user)

        result = await set_user_role(db, user_id=1, tenant_id=1, role=role)

        assert mock_user.role == role
        db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_in_tenant_raises_409_on_duplicate_username():
    existing_user = MagicMock()
    db = _make_db(scalar_result=existing_user)

    data = UserAdminCreate(
        username="duplicate",
        email="dup@example.com",
        password="password123",
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_user_in_tenant(db, tenant_id=1, data=data)
    assert exc_info.value.status_code == 409
    assert "Username already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_user_in_tenant_raises_409_on_duplicate_email():
    # First call (username check) returns None; second call (email check) returns existing
    execute_result_no_match = MagicMock()
    execute_result_no_match.scalar_one_or_none.return_value = None

    existing_user = MagicMock()
    execute_result_match = MagicMock()
    execute_result_match.scalar_one_or_none.return_value = existing_user

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[execute_result_no_match, execute_result_match])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = UserAdminCreate(
        username="newuser",
        email="duplicate@example.com",
        password="password123",
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_user_in_tenant(db, tenant_id=1, data=data)
    assert exc_info.value.status_code == 409
    assert "Email already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_user_in_tenant_creates_user_successfully():
    execute_result_no_match = MagicMock()
    execute_result_no_match.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result_no_match)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    data = UserAdminCreate(
        username="newuser",
        email="new@example.com",
        password="password123",
        role="Viewer",
    )
    await create_user_in_tenant(db, tenant_id=5, data=data)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    added_user = db.add.call_args[0][0]
    assert added_user.username == "newuser"
    assert added_user.tenant_id == 5
    assert added_user.role == "Viewer"


@pytest.mark.asyncio
async def test_deactivate_user_sets_is_active_false():
    mock_user = MagicMock()
    mock_user.is_active = True
    db = _make_db(scalar_result=mock_user)

    await deactivate_user(db, user_id=1, tenant_id=1)

    assert mock_user.is_active is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_user_patches_username_and_email():
    mock_user = MagicMock()
    mock_user.username = "old"
    mock_user.email = "old@example.com"

    # First call: get_user (returns mock_user)
    # Second call: username uniqueness check (returns None — no conflict)
    # Third call: email uniqueness check (returns None — no conflict)
    result_user = MagicMock()
    result_user.scalar_one_or_none.return_value = mock_user

    result_no_match = MagicMock()
    result_no_match.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_user, result_no_match, result_no_match])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    data = UserAdminUpdate(username="new", email="new@example.com")
    await update_user(db, user_id=1, tenant_id=1, data=data)

    assert mock_user.username == "new"
    assert mock_user.email == "new@example.com"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_user_raises_409_on_duplicate_username():
    mock_user = MagicMock()
    mock_user.username = "old"

    # First call: get_user (returns mock_user)
    # Second call: username uniqueness check (returns a conflicting user)
    result_user = MagicMock()
    result_user.scalar_one_or_none.return_value = mock_user

    existing_user = MagicMock()
    result_conflict = MagicMock()
    result_conflict.scalar_one_or_none.return_value = existing_user

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_user, result_conflict])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    data = UserAdminUpdate(username="taken")
    with pytest.raises(HTTPException) as exc_info:
        await update_user(db, user_id=1, tenant_id=1, data=data)
    assert exc_info.value.status_code == 409
    assert "Username already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_user_raises_409_on_duplicate_email():
    mock_user = MagicMock()
    mock_user.email = "old@example.com"

    # First call: get_user (returns mock_user)
    # Second call: email uniqueness check (returns a conflicting user)
    result_user = MagicMock()
    result_user.scalar_one_or_none.return_value = mock_user

    existing_user = MagicMock()
    result_conflict = MagicMock()
    result_conflict.scalar_one_or_none.return_value = existing_user

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_user, result_conflict])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    data = UserAdminUpdate(email="taken@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await update_user(db, user_id=1, tenant_id=1, data=data)
    assert exc_info.value.status_code == 409
    assert "Email already exists" in exc_info.value.detail
