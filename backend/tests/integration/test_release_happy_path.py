"""Happy path: instantiate from template → book envs → transition through all states → pass gates → complete."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.user import Tenant, User
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.booking_lifecycle import BookingType
from app.db.models.lifecycle import LifecycleTemplate
from app.core.security import get_password_hash


# ── Local fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """An authenticated HTTP client for the `tenant`/`user` fixtures."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username,
            "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def environment(db_session, tenant) -> Environment:
    """A persisted Environment in the `tenant` fixture."""
    env = Environment(
        tenant_id=tenant.id,
        name="SIT-ENV-01",
        environment_type="sit",
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture(scope="function")
async def booking_type(db_session, tenant) -> BookingType:
    """A BookingType with a minimal lifecycle template."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="booking",
        name="default-happy-path",
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
        tenant_id=tenant.id,
        name="Happy Path Standard",
        lifecycle_template_id=tpl.id,
    )
    db_session.add(bt)
    await db_session.commit()
    await db_session.refresh(bt)
    return bt


@pytest_asyncio.fixture(scope="function")
async def full_release_lifecycle_template(db_session, tenant) -> LifecycleTemplate:
    """A LifecycleTemplate with the full 5-state release lifecycle."""
    template = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Full Major Lifecycle",
        description="",
        is_default=False,
        definition={
            "states": [
                {"key": "draft",             "label": "Draft",              "is_initial": True,  "is_terminal": False},
                {"key": "submitted",         "label": "Submitted",          "is_initial": False, "is_terminal": False},
                {"key": "approved",          "label": "Approved",           "is_initial": False, "is_terminal": False},
                {"key": "in_progress",       "label": "In Progress",        "is_initial": False, "is_terminal": False},
                {"key": "ready_for_release", "label": "Ready for Release",  "is_initial": False, "is_terminal": False},
                {"key": "completed",         "label": "Completed",          "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft",             "to_state": "submitted",         "allowed_roles": ["Admin"]},
                {"from_state": "submitted",         "to_state": "approved",          "allowed_roles": ["Admin"]},
                {"from_state": "approved",          "to_state": "in_progress",       "allowed_roles": ["Admin"]},
                {"from_state": "in_progress",       "to_state": "ready_for_release", "allowed_roles": ["Admin"]},
                {"from_state": "ready_for_release", "to_state": "completed",         "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft":             {"standard_fields": {}, "custom_fields": {}},
                "submitted":         {"standard_fields": {}, "custom_fields": {}},
                "approved":          {"standard_fields": {}, "custom_fields": {}},
                "in_progress":       {"standard_fields": {}, "custom_fields": {}},
                "ready_for_release": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template


# ── Test ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_happy_path_from_template(
    authed_client: AsyncClient,
    tenant,
    user,
    system,
    environment,
    booking_type,
    full_release_lifecycle_template,
    db_session,
):
    # ── 1. Create a release template ─────────────────────────────────────────
    tmpl_resp = await authed_client.post("/api/v1/release-templates", json={
        "name": "Standard Major",
        "release_type": "Major",
        "default_lifecycle_template_id": full_release_lifecycle_template.id,
        "phases": [
            {"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []},
            {"name": "UAT", "order": 2, "default_duration_days": 5, "activities": []},
        ],
        "gates": [
            {"name": "SIT Exit", "phase_name": "SIT", "acceptance_criteria": "zero sev1"},
            {"name": "UAT Exit", "phase_name": "UAT", "acceptance_criteria": "signed off"},
        ],
    })
    assert tmpl_resp.status_code == 201, tmpl_resp.text
    tmpl_id = tmpl_resp.json()["id"]

    # ── 2. Instantiate a release from the template ───────────────────────────
    inst_resp = await authed_client.post(
        f"/api/v1/release-templates/{tmpl_id}/instantiate",
        json={"name": "R1", "target_date": "2026-05-01T00:00:00+00:00"},
    )
    assert inst_resp.status_code == 201, inst_resp.text
    release_id = inst_resp.json()["id"]

    # ── 3. Add a system role (changing) ──────────────────────────────────────
    sys_resp = await authed_client.post(
        f"/api/v1/releases/{release_id}/systems",
        json={"system_id": system.id, "role": "changing"},
    )
    assert sys_resp.status_code == 201, sys_resp.text

    # ── 4. Verify phases and gates materialised ───────────────────────────────
    phases = (await authed_client.get(f"/api/v1/releases/{release_id}/phases")).json()
    assert {p["name"] for p in phases} == {"SIT", "UAT"}
    gates = (await authed_client.get(f"/api/v1/releases/{release_id}/gates")).json()
    assert {g["name"] for g in gates} == {"SIT Exit", "UAT Exit"}

    # ── 5. Book an environment for the SIT phase ─────────────────────────────
    # Link the environment to the system via EnvironmentSystem so that
    # derive_and_set_context_tag can match the 'changing' role → 'deployment'.
    env_sys = EnvironmentSystem(
        environment_id=environment.id,
        system_id=system.id,
        tenant_id=tenant.id,
    )
    db_session.add(env_sys)
    await db_session.flush()

    sit_phase_id = next(p["id"] for p in phases if p["name"] == "SIT")
    book_resp = await authed_client.post(
        f"/api/v1/releases/{release_id}/bookings",
        json={
            "environment_id": environment.id,
            "phase_id": sit_phase_id,
            "start": "2026-04-25T00:00:00+00:00",
            "end":   "2026-04-30T00:00:00+00:00",
            "booking_type_id": booking_type.id,
        },
    )
    assert book_resp.status_code == 201, book_resp.text

    # ── 6. Verify context_tag == 'deployment' on the booking request ──────────
    # context_tag lives on BookingRequest, not on Booking.
    # Fetch the booking list for the release to get the booking id, then use
    # the bookings detail endpoint to reach the booking_request.
    booking_id = book_resp.json()["id"]
    from sqlalchemy import select
    from app.db.models.booking import Booking
    from app.db.models.booking_request import BookingRequest

    booking_row = (
        await db_session.execute(select(Booking).where(Booking.id == booking_id))
    ).scalar_one()
    br_row = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id == booking_row.booking_request_id)
        )
    ).scalar_one()
    assert str(br_row.context_tag.value if hasattr(br_row.context_tag, "value") else br_row.context_tag) == "deployment"

    # ── 7. Transition through the full lifecycle ──────────────────────────────
    for to_state in ["submitted", "approved", "in_progress", "ready_for_release", "completed"]:
        t_resp = await authed_client.post(
            f"/api/v1/releases/{release_id}/transition",
            json={"to_state": to_state},
        )
        assert t_resp.status_code == 200, (to_state, t_resp.text)
        assert t_resp.json()["status"] == to_state

    # ── 8. Pass all gates ────────────────────────────────────────────────────
    for g in gates:
        g_resp = await authed_client.post(
            f"/api/v1/gates/{g['id']}/pass",
            json={"notes": "ok"},
        )
        assert g_resp.status_code == 200, g_resp.text

    # ── 9. Confirm actual_date is stamped on the terminal release ─────────────
    final = (await authed_client.get(f"/api/v1/releases/{release_id}")).json()
    assert final["status"] == "completed"
    assert final["actual_date"] is not None
