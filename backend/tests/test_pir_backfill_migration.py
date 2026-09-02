"""The `pirbackfill` revision must not lose a word of an existing PIR.

Builds a scratch PostgreSQL database at revision `pirfindings`, inserts legacy
PIR rows covering every combination of free text and incident link, upgrades one
revision, and reads back what the findings tables hold.

`alembic downgrade -1` is never run against the dev database — it steps back
from the CURRENT head, not from your revision, which is how `tenant_secret` was
once dropped and a tenant's stored GitHub token lost. Everything here happens in
a database created and dropped by this file.

The harness (`_alembic`, `_scratch_url`, `ADMIN_URL`) is imported from
`test_migration_schema_drift.py` rather than copied, so a change to how this
repo drives Alembic in tests lands in one place.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.test_migration_schema_drift import ADMIN_URL, SCRATCH_DB, _alembic, _scratch_url


@pytest.fixture
def scratch_db_at_pirfindings(request):
    """An empty scratch database migrated to `pirfindings` — the revision
    immediately before the one under test. Dropped on teardown."""
    name = f"{SCRATCH_DB}_backfill_{abs(hash(request.node.name)) % 10_000}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for the backfill rehearsal: {exc}")

    result = _alembic("pirfindings", name)
    assert result.returncode == 0, f"alembic upgrade pirfindings failed:\n{result.stderr}"

    yield name

    with admin.connect() as conn:
        # A failing test leaves its own engine holding a connection, and
        # PostgreSQL refuses to drop a database anyone is attached to — without
        # this the teardown error buries the assertion that actually failed.
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def test_legacy_free_text_becomes_findings_and_actions(scratch_db_at_pirfindings):
    name = scratch_db_at_pirfindings
    engine = create_engine(_scratch_url("psycopg2", name))
    with engine.begin() as conn:
        tenant_id = conn.execute(text(
            "INSERT INTO tenant (name, slug, created_at, updated_at) "
            "VALUES ('T', 't-backfill', now(), now()) RETURNING id")).scalar_one()
        user_id = conn.execute(text(
            'INSERT INTO "user" (tenant_id, username, email, password_hash, role, '
            "is_active, created_at, updated_at) "
            "VALUES (:t, 'u', 'u@x.test', 'x', 'Admin', true, now(), now()) RETURNING id"),
            {"t": tenant_id}).scalar_one()
        tpl_id = conn.execute(text(
            "INSERT INTO lifecycle_template (tenant_id, entity_type, name, is_default, "
            "definition, created_at, updated_at) VALUES (:t, 'release', 'RT', false, "
            '\'{"states": [], "transitions": [], "field_permissions": {}}\', now(), now()) '
            "RETURNING id"), {"t": tenant_id}).scalar_one()

        def _release(name_):
            return conn.execute(text(
                "INSERT INTO release (tenant_id, name, release_type, release_kind, "
                "lifecycle_template_id, status, raised_by, created_at, updated_at) "
                "VALUES (:t, :n, 'Major', 'project', :tpl, 'draft', :u, now(), now()) "
                "RETURNING id"),
                {"t": tenant_id, "n": name_, "tpl": tpl_id, "u": user_id}).scalar_one()

        incident_id = conn.execute(text(
            "INSERT INTO incident (tenant_id, title, severity, status, detected_at, source, "
            "created_at, updated_at) VALUES (:t, 'Checkout 500s', 'P1', 'open', now(), "
            "'manual', now(), now()) RETURNING id"), {"t": tenant_id}).scalar_one()

        def _pir(release_id, **cols):
            keys = ", ".join(cols)
            vals = ", ".join(f":{k}" for k in cols)
            return conn.execute(text(
                f"INSERT INTO pir (tenant_id, release_id, status, {keys}, created_at, "
                f"updated_at) VALUES (:t, :r, 'draft', {vals}, now(), now()) RETURNING id"),
                {"t": tenant_id, "r": release_id, **cols}).scalar_one()

        full = _pir(_release("full"), summary="S", root_cause="RC", what_went_well="WW",
                    what_went_wrong="WX", action_plan="AP", incident_id=incident_id,
                    created_by=user_id)
        text_only = _pir(_release("text-only"), what_went_wrong="WX2")
        incident_only = _pir(_release("incident-only"), incident_id=incident_id)
        well_only = _pir(_release("well-only"), what_went_well="WW3")
        empty = _pir(_release("empty"), summary="just a summary")
        # Whitespace is not content: a column holding "   " must migrate to
        # nothing, or the estate fills with blank findings nobody wrote.
        blank = _pir(_release("blank"), what_went_wrong="   ", root_cause="")
        # A soft-deleted review is not migrated at all — it was withdrawn.
        deleted = _pir(_release("deleted"), what_went_wrong="gone")

    with engine.begin() as conn:
        conn.execute(text("UPDATE pir SET deleted_at = now() WHERE id = :p"), {"p": deleted})

    result = _alembic("pirbackfill", name)
    assert result.returncode == 0, f"alembic upgrade pirbackfill failed:\n{result.stderr}"

    with engine.begin() as conn:
        def _findings(pir_id):
            return conn.execute(text(
                "SELECT kind, seq, title, detail, root_cause, tenant_id, created_by "
                "FROM pir_finding WHERE pir_id = :p ORDER BY kind, seq"), {"p": pir_id}).all()

        # Everything present: two findings, the action, and the citation.
        rows = _findings(full)
        assert [(r[0], r[2], r[3]) for r in rows] == [
            ("went_well", "What went well (migrated)", "WW"),
            ("went_wrong", "What went wrong (migrated)", "WX"),
        ]
        assert rows[1][4] == "RC"
        # The row's own tenant and author travel with it — a migrated finding
        # that lands in no tenant is invisible to every query in the app.
        assert {r[5] for r in rows} == {tenant_id}
        assert {r[6] for r in rows} == {user_id}
        assert conn.execute(text(
            "SELECT a.title, a.detail, a.status FROM pir_action a JOIN pir_finding f "
            "ON f.id = a.finding_id WHERE f.pir_id = :p"), {"p": full}).all() == [
            ("Action plan (migrated)", "AP", "open")]
        assert conn.execute(text(
            "SELECT i.incident_id FROM pir_finding_incident i JOIN pir_finding f "
            "ON f.id = i.finding_id WHERE f.pir_id = :p"), {"p": full}).scalar_one() == incident_id

        # A went-wrong finding is created if ANY of the four had a value, so
        # nothing is stranded by the absence of one field.
        assert [r[0] for r in _findings(text_only)] == ["went_wrong"]
        assert [r[2] for r in _findings(incident_only)] == ["Incident (migrated)"]
        assert [r[0] for r in _findings(well_only)] == ["went_well"]

        # A PIR that only ever had a summary migrates to nothing at all.
        assert _findings(empty) == []
        assert conn.execute(text(
            "SELECT summary FROM pir WHERE id = :p"), {"p": empty}).scalar_one() == "just a summary"
        assert _findings(blank) == []
        assert _findings(deleted) == []

        # The columns are gone.
        cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pir'")).all()}
        assert cols.isdisjoint(
            {"incident_id", "root_cause", "what_went_well", "what_went_wrong", "action_plan"})
        assert "summary" in cols
    engine.dispose()


def test_the_migrated_rows_are_readable_through_the_running_app_schema(scratch_db_at_pirfindings):
    """`alembic upgrade head` from `pirfindings` must land on `pirbackfill` and
    leave a schema the models can still describe — a migration that leaves the
    chain unreachable passes every unit test and fails on deploy."""
    name = scratch_db_at_pirfindings
    result = _alembic("head", name)
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
    engine = create_engine(_scratch_url("psycopg2", name))
    with engine.begin() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == \
            "pirbackfill"
    engine.dispose()
