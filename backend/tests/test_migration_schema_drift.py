"""Guard against drift between Alembic migrations and the SQLAlchemy models.

The rest of the suite builds its schema with ``Base.metadata.create_all`` on
SQLite, which means the migration chain is never exercised. A migration that
forgets a column therefore passes every test while producing a broken database
on a clean deploy — exactly how six tables ended up without ``created_at`` /
``updated_at``.

This test builds a throwaway PostgreSQL database with ``alembic upgrade head``
and diffs the result against ``Base.metadata``. It is skipped when no
PostgreSQL server is reachable so local SQLite-only runs stay green; CI is
expected to provide one.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from app.db.base import Base
import app.db.models  # noqa: F401  — registers every model on Base.metadata


BACKEND_DIR = Path(__file__).resolve().parents[1]

# Sync (psycopg2) URLs for the admin connection; alembic gets the async URL.
ADMIN_URL = os.environ.get(
    "MIGRATION_TEST_ADMIN_URL",
    "postgresql+psycopg2://envmgr:envmgr_dev_password@localhost:5432/postgres",
)
SCRATCH_DB = os.environ.get("MIGRATION_TEST_DB_NAME", "envmgr_migration_check")


def _scratch_url(driver: str, name: str = SCRATCH_DB) -> str:
    base = ADMIN_URL.replace("postgresql+psycopg2://", f"postgresql+{driver}://")
    return base.rsplit("/", 1)[0] + f"/{name}"


def _alembic(target: str, name: str = SCRATCH_DB) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": ".", "DATABASE_URL": _scratch_url("asyncpg", name)},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch_database(request):
    """Yield the name of an empty PostgreSQL database, dropped on teardown."""
    name = f"{SCRATCH_DB}_{abs(hash(request.node.name)) % 10_000}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for migration drift check: {exc}")

    yield name

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture
def migrated_schema(scratch_database):
    """Build a database from the full migration chain; yield its schema."""
    result = _alembic("head", scratch_database)
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"

    engine = create_engine(_scratch_url("psycopg2", scratch_database))
    with engine.connect() as conn:
        insp = inspect(conn)
        schema = {
            table: {col["name"] for col in insp.get_columns(table)}
            for table in insp.get_table_names()
            if table != "alembic_version"
        }
    engine.dispose()
    return schema


def test_upgrade_is_a_noop_when_create_all_already_supplied_the_columns(scratch_database):
    """Dev/test databases are bootstrapped by ``Base.metadata.create_all``, so they
    already carry every Base column. Migrating such a database must not fail."""
    stop_short = _alembic("7441806378e5", scratch_database)
    assert stop_short.returncode == 0, stop_short.stderr

    # Stand in for create_all having already created the columns.
    engine = create_engine(
        _scratch_url("psycopg2", scratch_database), isolation_level="AUTOCOMMIT"
    )
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE incident "
                "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            )
        )
    engine.dispose()

    finish = _alembic("head", scratch_database)
    assert finish.returncode == 0, (
        f"migrating a create_all-bootstrapped database failed:\n{finish.stderr}"
    )


def test_migrations_create_every_model_table(migrated_schema):
    expected = {table.name for table in Base.metadata.sorted_tables}
    missing = sorted(expected - set(migrated_schema))
    assert not missing, f"tables declared by models but never created by migrations: {missing}"


def test_migrations_create_every_model_column(migrated_schema):
    drift = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in migrated_schema:
            continue  # covered by test_migrations_create_every_model_table
        missing = sorted({c.name for c in table.columns} - migrated_schema[table.name])
        if missing:
            drift[table.name] = missing

    assert not drift, (
        "columns declared by models but never created by migrations "
        f"(a clean deploy would fail on these tables): {drift}"
    )
