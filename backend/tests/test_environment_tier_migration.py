"""The tier backfill, exercised against a real migrated database.

Skipped without PostgreSQL, like test_migration_schema_drift — migrations are
never run by the rest of the suite, which builds its schema with create_all.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

BACKEND_DIR = Path(__file__).resolve().parents[1]

ADMIN_URL = os.environ.get(
    "MIGRATION_TEST_ADMIN_URL",
    "postgresql+psycopg2://envmgr:envmgr_dev_password@localhost:5432/postgres",
)
SCRATCH_DB = "envmgr_tier_migration_check"


def _url(driver: str, name: str) -> str:
    base = ADMIN_URL.replace("postgresql+psycopg2://", f"postgresql+{driver}://")
    return base.rsplit("/", 1)[0] + f"/{name}"


def _alembic(target: str, name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": ".", "DATABASE_URL": _url("asyncpg", name)},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch_database():
    name = SCRATCH_DB
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for the tier migration check: {exc}")

    yield name

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture
def migrated(scratch_database):
    """Two tenants with mixed-case environment types, migrated to head."""
    before = _alembic("subsystemsource", scratch_database)
    assert before.returncode == 0, before.stderr

    engine = create_engine(_url("psycopg2", scratch_database), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (name, slug, is_active, created_at, updated_at) "
                "VALUES ('One', 'one', true, now(), now()), "
                "('Two', 'two', true, now(), now())"
            )
        )
        one, two = [r[0] for r in conn.execute(text("SELECT id FROM tenant ORDER BY id"))]
        for tenant_id, env_type, name in [
            (one, "SIT", "a"),
            (one, "sit", "b"),
            (one, "uat", "c"),
            (one, "imported", "d"),
            (two, "SIT", "e"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO environment "
                    "(tenant_id, name, environment_type, status, created_at, updated_at) "
                    "VALUES (:t, :n, :e, 'ACTIVE', now(), now())"
                ),
                {"t": tenant_id, "n": name, "e": env_type},
            )
    engine.dispose()

    after = _alembic("head", scratch_database)
    assert after.returncode == 0, f"upgrade to head failed:\n{after.stderr}"

    engine = create_engine(_url("psycopg2", scratch_database))
    yield engine, one, two
    engine.dispose()


def test_mixed_case_values_collapse_to_one_tier(migrated):
    engine, one, _ = migrated
    with engine.connect() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT et.name FROM environment e "
                    "JOIN environment_tier et ON et.id = e.tier_id "
                    "WHERE e.tenant_id = :t AND e.name IN ('a', 'b')"
                ),
                {"t": one},
            )
        ]
    assert names == ["SIT", "SIT"]


def test_an_unrecognised_value_survives_as_a_tenant_tier_with_no_category(migrated):
    engine, one, _ = migrated
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT et.name, et.category FROM environment e "
                "JOIN environment_tier et ON et.id = e.tier_id "
                "WHERE e.tenant_id = :t AND e.name = 'd'"
            ),
            {"t": one},
        ).one()
    assert row[0] == "imported"
    assert row[1] is None


def test_every_environment_has_a_tier(migrated):
    engine, _, _ = migrated
    with engine.connect() as conn:
        orphans = conn.execute(
            text("SELECT count(*) FROM environment WHERE tier_id IS NULL")
        ).scalar_one()
    assert orphans == 0


def test_no_tier_crosses_a_tenant_boundary(migrated):
    engine, _, _ = migrated
    with engine.connect() as conn:
        leaked = conn.execute(
            text(
                "SELECT count(*) FROM environment e "
                "JOIN environment_tier et ON et.id = e.tier_id "
                "WHERE et.tenant_id <> e.tenant_id"
            )
        ).scalar_one()
    assert leaked == 0


def test_the_old_column_is_gone(migrated):
    """test_migration_schema_drift compares only columns the models declare, so
    a forgotten drop_column would pass it. Assert the drop directly."""
    engine, _, _ = migrated
    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("environment")}
    assert "environment_type" not in columns
    assert {"tier_id", "owner_user_id", "expires_at"} <= columns
