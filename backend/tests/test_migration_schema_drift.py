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


def _alembic(
    target: str, name: str = SCRATCH_DB, command: str = "upgrade"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
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


def _seed_group_linked_booking(scratch_database) -> int:
    """Build the full parent chain by hand and insert a booking whose
    ``environment_group_id`` points at a real, non-null ``environment_group``
    row. Returns the booking id. Uses AUTOCOMMIT so the row is durably
    visible to the separate ``alembic`` subprocess invocations that follow."""
    engine = create_engine(
        _scratch_url("psycopg2", scratch_database), isolation_level="AUTOCOMMIT"
    )
    with engine.connect() as conn:
        tenant_id = conn.execute(
            text("INSERT INTO tenant (name, slug) VALUES ('T', 't') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(
            text(
                'INSERT INTO "user" '
                "(tenant_id, username, email, password_hash, role, is_active) "
                "VALUES (:t, 'u', 'u@x.com', 'h', 'Admin', true) RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        tier_id = conn.execute(
            text(
                "INSERT INTO environment_tier (tenant_id, name) "
                "VALUES (:t, 'Tier1') RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        env_id = conn.execute(
            text(
                "INSERT INTO environment (name, tenant_id, tier_id) "
                "VALUES ('Env1', :t, :tier) RETURNING id"
            ),
            {"t": tenant_id, "tier": tier_id},
        ).scalar_one()
        lifecycle_id = conn.execute(
            text(
                "INSERT INTO lifecycle_template "
                "(tenant_id, name, definition, entity_type) "
                "VALUES (:t, 'LC', '{}'::jsonb, 'booking') RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        booking_type_id = conn.execute(
            text(
                "INSERT INTO booking_type (tenant_id, name, lifecycle_template_id) "
                "VALUES (:t, 'BT', :lc) RETURNING id"
            ),
            {"t": tenant_id, "lc": lifecycle_id},
        ).scalar_one()
        group_id = conn.execute(
            text(
                "INSERT INTO environment_group (tenant_id, name, is_active) "
                "VALUES (:t, 'GroupA', true) RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        booking_request_id = conn.execute(
            text(
                "INSERT INTO booking_request "
                "(tenant_id, project_name, booking_type_id, start_date, end_date, booked_by) "
                "VALUES (:t, 'Regression', :bt, now(), now() + interval '1 day', :u) "
                "RETURNING id"
            ),
            {"t": tenant_id, "bt": booking_type_id, "u": user_id},
        ).scalar_one()
        booking_id = conn.execute(
            text(
                "INSERT INTO booking "
                "(environment_id, environment_group_id, start_date, end_date, "
                "tenant_id, status, booking_request_id) "
                "VALUES (:env, :grp, now(), now() + interval '1 day', :t, 'draft', :br) "
                "RETURNING id"
            ),
            {"env": env_id, "grp": group_id, "t": tenant_id, "br": booking_request_id},
        ).scalar_one()
    engine.dispose()
    return booking_id


def test_upgrade_after_downgrade_nulls_orphaned_booking_group_id(scratch_database):
    """``envgroups`` downgrade correctly leaves ``booking.environment_group_id``
    and its value in place while dropping the table that value pointed at —
    the column predates the revision and downgrade must not destroy it. But
    that column has been unconstrained since the March booking migration, so
    an orphaned value there isn't only a downgrade artifact; nothing has ever
    stopped one arising by other means either. ``upgrade()`` must null any
    orphan before re-adding the FK, or the very next ``upgrade head`` fails
    with ForeignKeyViolationError and can never succeed on its own. The fix
    nulls a dangling reference — it must not touch the booking row itself.
    """
    up = _alembic("head", scratch_database)
    assert up.returncode == 0, up.stderr

    booking_id = _seed_group_linked_booking(scratch_database)

    # `envgroups-1`, NOT `-1`: this test is about the `envgroups` revision, and
    # a bare `-1` means "one step back from the CURRENT head" — the moment any
    # revision lands on top of envgroups, `-1` reverses that one instead and
    # this test silently starts asserting nothing (it failed outright when
    # `agreementack` landed, which is the lucky version of that). Same trap as
    # the dev-database warning in CLAUDE.md, one level up.
    #
    # Alembic's relative-to-a-revision syntax says "one step back from
    # envgroups" literally, so it stays correct if a revision is later inserted
    # either side of it. Naming envgroups' current PARENT (`projects`) instead
    # would encode the assumption that it stays the parent, and would quietly
    # widen the window under test the day something is inserted between them.
    down = _alembic("envgroups-1", scratch_database, command="downgrade")
    assert down.returncode == 0, down.stderr

    up_again = _alembic("head", scratch_database)
    assert up_again.returncode == 0, (
        "upgrade head after downgrade failed — an orphaned "
        f"booking.environment_group_id was left for the new FK to reject:\n{up_again.stderr}"
    )

    engine = create_engine(_scratch_url("psycopg2", scratch_database))
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, environment_group_id FROM booking WHERE id = :id"),
            {"id": booking_id},
        ).one()
    engine.dispose()

    assert row.id == booking_id, "the booking row itself must survive the cycle"
    assert row.environment_group_id is None, (
        "the orphaned reference must be nulled by upgrade(), not left dangling"
    )
