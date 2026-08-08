"""index usage_agreement on the pair A3's coverage lookup correlates on

Revision ID: agreementidx
Revises: agreementack
Create Date: 2026-08-08 14:00:00.000000

Additive, and nothing but an index: one `CREATE INDEX` on
`usage_agreement (project_id, environment_id)`.

WHY. `agreement_gap_service.covered_exists_clause` correlates on exactly that
pair — `UsageAgreement.project_id == BookingRequest.project_id` and
`UsageAgreement.environment_id == Booking.environment_id` — and it runs on every
`GET /bookings` load (once for the page, and again as the `?agreement_gap=`
filter). A1 gave each of those columns its own single-column index, which forces
the planner to pick one and filter the rest; this is the pair the query asks for.

NOT prefixed with `tenant_id`, though the clause filters it: a `project_id`
identifies one project, which belongs to one tenant, so leading with `tenant_id`
would only put the low-cardinality column first. `deleted_at` is left out for the
reason it is left out of every other index on this table — it is the majority
value, not a discriminator.

NOTE FOR WHOEVER APPLIES THIS TO A LONG-LIVED DATABASE: `init_db()` calls
`create_all`, so a running backend may already have built this index while
`alembic_version` still sits at `agreementack`, and the upgrade then fails with
DuplicateTable. Drop the stray index and run the migration properly — do NOT
stamp past it, or the next environment gets no index at all.

`tests/test_migration_schema_drift.py` compares column NAME SETS only and cannot
see this change at all. It was verified by diffing `pg_indexes`' full `indexdef`
between two scratch databases, one built with `alembic upgrade head` and one with
`create_all`.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'agreementidx'
down_revision: Union[str, None] = 'agreementack'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_agreement_project_env",
        "usage_agreement",
        ["project_id", "environment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_agreement_project_env", table_name="usage_agreement")
