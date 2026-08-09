"""The one part of B2 with no precedent in this codebase: reaching inside the
`custom_fields` JSON column from SQL. It compiles to `->>` on PostgreSQL and
`json_extract` on SQLite, so it is tested on both legs before anything is
built on top of it."""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services.environment_compliance_service import custom_field_missing_clause
from tests.factories import ensure_environment_tier


async def _env(db, tenant_id, name, custom_fields):
    tier = await ensure_environment_tier(db, tenant_id)
    env = Environment(
        name=name, tier_id=tier.id, tenant_id=tenant_id, custom_fields=custom_fields
    )
    db.add(env)
    await db.flush()
    return env


@pytest.mark.asyncio
async def test_missing_key_absent_null_and_blank_all_count_as_missing(
    db_session, test_tenant
):
    await _env(db_session, test_tenant.id, "absent", {"other": "x"})
    await _env(db_session, test_tenant.id, "explicit-null", {"cost_centre": None})
    await _env(db_session, test_tenant.id, "blank", {"cost_centre": "   "})
    await _env(db_session, test_tenant.id, "no-json-at-all", None)
    await _env(db_session, test_tenant.id, "present", {"cost_centre": "CC-1"})

    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("cost_centre"),
            )
        )
    ).scalars().all()

    assert sorted(rows) == ["absent", "blank", "explicit-null", "no-json-at-all"]


@pytest.mark.asyncio
async def test_a_numeric_value_counts_as_present(db_session, test_tenant):
    """A custom field of type `number` stores an int, not a string. Casting to
    text must not make 0 look absent — `0` is a supplied value."""
    await _env(db_session, test_tenant.id, "zero", {"seats": 0})
    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("seats"),
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_boolean_false_value_counts_as_present(db_session, test_tenant):
    """The docstring pairs `false` with `0` as a supplied value, not a missing
    one — a `boolean` custom field storing `false` is still an answer."""
    await _env(db_session, test_tenant.id, "false-flag", {"enabled": False})
    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("enabled"),
            )
        )
    ).scalars().all()
    assert rows == []


def test_field_key_containing_a_double_quote_is_refused():
    """SQLite's JSON comparator builds its path by raw string concatenation
    (`$."` + key + `"`), so a key containing `"` compiles to a malformed path
    on SQLite while PostgreSQL resolves it fine — the two engines would
    silently disagree about whether the field is missing. The guard must
    raise before either engine ever sees the clause."""
    with pytest.raises(ValueError):
        custom_field_missing_clause('cost_centre" OR 1=1 --')


def test_field_key_safe_charset_is_pinned():
    """Mirrors CustomFieldDefinition's own validation
    (^[a-z][a-z0-9_]*$, app/api/v1/schemas/custom_field.py). If that charset
    is ever widened, this must fail loudly rather than let the two engines
    quietly diverge on a key `custom_field_missing_clause` was never checked
    against."""
    for key in ("cost_centre", "seats2", "a", "a_b_c9"):
        custom_field_missing_clause(key)  # must not raise

    for key in ("Cost_Centre", "-bad", "has space", 'has"quote', "has'quote", "has.dot"):
        with pytest.raises(ValueError):
            custom_field_missing_clause(key)
