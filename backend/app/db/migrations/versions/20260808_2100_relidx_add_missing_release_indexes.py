"""add the tenant_id and FK indexes the release tables' models declare

Revision ID: relidx
Revises: agreementidx
Create Date: 2026-08-08

The models declare `index=True` on these columns; the hand-written migrations
that created the tables simply omitted them. So `Base.metadata.create_all` —
which is how BOTH conftest legs build the test schema — has had them all along
and production, which is migration-built, has not. The suite therefore ran
against indexes production does not have.

WHAT THIS DOES NOT INCLUDE, and why. Comparing the two schemas by index
DEFINITION rather than by name (names differ for identical indexes, which is
how an earlier pass produced a false alarm) gives 57 `create_all`-only indexes:

  * 40 are single-column `(id)` indexes, redundant with the primary key's own
    index. Left alone deliberately — the fix there is to stop DECLARING them,
    which changes the test schema rather than production, and is not this
    migration's business.
  * 3 are already served by a non-partial composite's leading column
    (e.g. `gate_criterion (tenant_id)` by `(tenant_id, assigned_to_user_id,
    status)`).
  * the 14 below are genuinely absent.

Four of the 14 are arguably redundant for THIS application's access patterns —
`gate_criterion (gate_id)` and `(assigned_to_user_id)`, and the two history
tables' `(change_id)`, each already fronted by a composite that leads with
`tenant_id`, and every query here filters `tenant_id`. They are added anyway,
for two reasons: a bare FK index also serves constraint checking and joins in
the reverse direction, which a `(tenant_id, x)` composite does not; and
converging the two schemas is the point of the exercise, since every index left
divergent is one a future drift check has to carve out by hand.

Nothing here is unique and nothing carries a WHERE clause, so this is additive
and reversible with no data implications. Note `tests/test_migration_schema_drift.py`
cannot see any of this — it compares column NAME SETS only.
"""
from alembic import op

revision = "relidx"
down_revision = "agreementidx"
branch_labels = None
depends_on = None


# (index name, table, column) — names match what `create_all` emits, so the two
# schemas converge by name as well as by definition.
INDEXES = [
    ("ix_gate_criterion_assigned_to_user_id", "gate_criterion", "assigned_to_user_id"),
    ("ix_gate_criterion_gate_id", "gate_criterion", "gate_id"),
    ("ix_release_change_system_id", "release_change", "system_id"),
    ("ix_release_change_tenant_id", "release_change", "tenant_id"),
    ("ix_release_change_release_history_change_id", "release_change_release_history", "change_id"),
    ("ix_release_change_status_history_change_id", "release_change_status_history", "change_id"),
    ("ix_release_dependency_depends_on_release_id", "release_dependency", "depends_on_release_id"),
    ("ix_release_dependency_tenant_id", "release_dependency", "tenant_id"),
    ("ix_release_event_event_type_id", "release_event", "event_type_id"),
    ("ix_release_event_tenant_id", "release_event", "tenant_id"),
    ("ix_release_gate_tenant_id", "release_gate", "tenant_id"),
    ("ix_release_system_system_id", "release_system", "system_id"),
    ("ix_release_system_tenant_id", "release_system", "tenant_id"),
    ("ix_scope_change_kind_rule_tenant_id", "scope_change_kind_rule", "tenant_id"),
]


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
