"""The `closeout` revision flags existing project release templates by state
KEY and leaves renamed keys alone; it inserts no state and no transition.

Same harness as test_pir_backfill_migration.py: a scratch PostgreSQL database
pinned at the previous revision, rows inserted with raw SQL, one upgrade,
read back. Skips when there is no PostgreSQL server.
"""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.test_migration_schema_drift import ADMIN_URL, SCRATCH_DB, _alembic, _scratch_url

_DEFAULT_SHAPE = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "ready_for_release", "label": "Ready", "is_initial": False, "is_terminal": False},
        {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "CWI", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [{"from_state": "draft", "to_state": "completed", "label": "Go", "allowed_roles": ["Admin"]}],
    "field_permissions": {},
}
_RENAMED_SHAPE = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "live", "label": "Live", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [], "field_permissions": {},
}


@pytest.fixture
def scratch_db_at_gonogo(request):
    name = f"{SCRATCH_DB}_closeout_{abs(hash(request.node.name)) % 10_000}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for the closeout migration rehearsal: {exc}")
    result = _alembic("gonogo", name)
    assert result.returncode == 0, f"alembic upgrade gonogo failed:\n{result.stderr}"
    yield name
    with admin.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def _insert_template(conn, tenant_id, name, kind, shape):
    return conn.execute(text(
        "INSERT INTO lifecycle_template (tenant_id, entity_type, name, is_default, applies_to_kind, "
        "definition, created_at, updated_at) VALUES (:t, 'release', :n, false, :k, :d, now(), now()) "
        "RETURNING id"), {"t": tenant_id, "n": name, "k": kind, "d": json.dumps(shape)}).scalar_one()


def test_flags_land_on_the_named_states_only(scratch_db_at_gonogo):
    name = scratch_db_at_gonogo
    engine = create_engine(_scratch_url("psycopg2", name))
    with engine.begin() as conn:
        tenant_id = conn.execute(text(
            "INSERT INTO tenant (name, slug, created_at, updated_at) "
            "VALUES ('T', 't-closeout', now(), now()) RETURNING id")).scalar_one()
        default_id = _insert_template(conn, tenant_id, "Major", "project", _DEFAULT_SHAPE)
        renamed_id = _insert_template(conn, tenant_id, "Renamed", "project", _RENAMED_SHAPE)
        enterprise_id = _insert_template(conn, tenant_id, "Ent", "enterprise", _DEFAULT_SHAPE)

    result = _alembic("closeout", name)
    assert result.returncode == 0, f"alembic upgrade closeout failed:\n{result.stderr}"

    with engine.connect() as conn:
        def states(tid):
            raw = conn.execute(text("SELECT definition FROM lifecycle_template WHERE id = :i"),
                               {"i": tid}).scalar_one()
            defn = raw if isinstance(raw, dict) else json.loads(raw)
            return {s["key"]: s for s in defn["states"]}, defn

        by_key, defn = states(default_id)
        assert by_key["completed"]["is_closed"] is True and by_key["completed"]["marks_deployed"] is True
        assert by_key["completed_with_issues"]["is_closed"] is True
        assert by_key["completed_with_issues"]["is_failed"] is True  # untouched
        assert by_key["backed_out"]["is_closed"] is True
        assert "marks_deployed" not in by_key["backed_out"]
        assert "is_closed" not in by_key["cancelled"]
        assert len(defn["states"]) == 6 and len(defn["transitions"]) == 1  # nothing inserted

        renamed, _ = states(renamed_id)
        assert "is_closed" not in renamed["live"]

        ent, _ = states(enterprise_id)
        assert "is_closed" not in ent["completed"]

        names = {r[0] for r in conn.execute(text(
            "SELECT name FROM release_event_type WHERE tenant_id = :t AND is_system"), {"t": tenant_id})}
        assert {"Declared stable", "Stability declaration withdrawn",
                "Ops handover confirmed", "Ops handover withdrawn"} <= names

        assert conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'test_phase' AND column_name = 'kind'")).scalar_one().startswith("'test'")

    down = _alembic("gonogo", name, command="downgrade")
    assert down.returncode == 0, down.stderr
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT definition FROM lifecycle_template WHERE id = :i"),
                           {"i": default_id}).scalar_one()
        defn = raw if isinstance(raw, dict) else json.loads(raw)
        completed = next(s for s in defn["states"] if s["key"] == "completed")
        assert "is_closed" not in completed and "marks_deployed" not in completed
        cwi = next(s for s in defn["states"] if s["key"] == "completed_with_issues")
        assert cwi["is_failed"] is True  # pre-C6 flag survives the downgrade
    engine.dispose()
