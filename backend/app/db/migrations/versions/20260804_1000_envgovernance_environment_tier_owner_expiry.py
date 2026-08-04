"""environment governance — tier table, owner, expiry

Revision ID: envgovernance
Revises: subsystemsource
Create Date: 2026-08-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envgovernance'
down_revision: Union[str, None] = 'subsystemsource'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A literal copy of app.services.environment_tier_defaults.STANDARD_TIERS,
# deliberately not an import: a migration reproduces the past and must not
# change meaning when that module gains a ninth tier.
STANDARD_TIERS = [
    {"name": "Dev",         "category": "dev",         "color": "#90A4AE", "display_order": 10},
    {"name": "SIT",         "category": "sit",         "color": "#42A5F5", "display_order": 20},
    {"name": "UAT",         "category": "uat",         "color": "#7E57C2", "display_order": 30},
    {"name": "Pre-Prod",    "category": "preprod",     "color": "#FFA726", "display_order": 40},
    {"name": "Performance", "category": "performance", "color": "#26A69A", "display_order": 50},
    {"name": "Training",    "category": "training",    "color": "#8D6E63", "display_order": 60},
    {"name": "Production",  "category": "production",  "color": "#EF5350", "display_order": 70},
    {"name": "Other",       "category": "other",       "color": "#BDBDBD", "display_order": 80},
]

# environment.environment_type was VARCHAR(100) and environment_tier.name is
# VARCHAR(200), so a value carried across can never overflow. Asserted rather
# than assumed, because SQLite would not complain and PostgreSQL would.
_TIER_NAME_LIMIT = 200

_tier_table = sa.table(
    "environment_tier",
    sa.column("id", sa.Integer),
    sa.column("tenant_id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("color", sa.String),
    sa.column("display_order", sa.Integer),
    sa.column("is_active", sa.Boolean),
)


def _backfill(conn) -> None:
    """Per tenant: seed the standard tiers, fold existing environment_type
    values onto them case-insensitively, and point every environment at one."""
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant"))]

    for tenant_id in tenant_ids:
        conn.execute(
            sa.insert(_tier_table),
            [
                {
                    "tenant_id": tenant_id,
                    "name": t["name"],
                    "category": t["category"],
                    "color": t["color"],
                    "display_order": t["display_order"],
                    "is_active": True,
                }
                for t in STANDARD_TIERS
            ],
        )

        by_lower_name = {
            name.lower(): tier_id
            for tier_id, name in conn.execute(
                sa.text(
                    "SELECT id, name FROM environment_tier WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        }
        other_id = by_lower_name["other"]

        existing_types = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT DISTINCT environment_type FROM environment "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ]

        for raw in existing_types:
            key = (raw or "").strip().lower()
            if not key:
                tier_id = other_id
            elif key in by_lower_name:
                # 'SIT' and 'sit' both land here — the standard spelling wins
                # and no tenant-specific duplicate is created.
                tier_id = by_lower_name[key]
            else:
                # A value the standard vocabulary does not cover — e.g. the
                # literal "imported" that excel_import_service used to write.
                # Kept as a tenant-specific tier with a NULL category so
                # nothing is silently bucketed into Other.
                name = raw.strip()[:_TIER_NAME_LIMIT]
                conn.execute(
                    sa.insert(_tier_table).values(
                        tenant_id=tenant_id,
                        name=name,
                        category=None,
                        color=None,
                        display_order=100,
                        is_active=True,
                    )
                )
                tier_id = conn.execute(
                    sa.text(
                        "SELECT id FROM environment_tier "
                        "WHERE tenant_id = :t AND name = :n"
                    ),
                    {"t": tenant_id, "n": name},
                ).scalar_one()
                by_lower_name[key] = tier_id

            if raw is None:
                conn.execute(
                    sa.text(
                        "UPDATE environment SET tier_id = :tier "
                        "WHERE tenant_id = :t AND environment_type IS NULL"
                    ),
                    {"tier": tier_id, "t": tenant_id},
                )
            else:
                conn.execute(
                    sa.text(
                        "UPDATE environment SET tier_id = :tier "
                        "WHERE tenant_id = :t AND environment_type = :v"
                    ),
                    {"tier": tier_id, "t": tenant_id, "v": raw},
                )


def upgrade() -> None:
    op.create_table(
        "environment_tier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(length=_TIER_NAME_LIMIT), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_environment_tier_tenant_id", "environment_tier", ["tenant_id"])
    # Base declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here, a migration-built database
    # differs from a create_all-built one — not caught by
    # test_migration_schema_drift.py, which compares only tables and columns.
    op.create_index("ix_environment_tier_id", "environment_tier", ["id"])

    # Added nullable so the backfill has somewhere to write; tightened to NOT
    # NULL below, which is also the check that the backfill reached every row.
    op.add_column("environment", sa.Column("tier_id", sa.Integer(), nullable=True))
    op.add_column("environment", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "environment", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_environment_tier_id", "environment", "environment_tier", ["tier_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_environment_owner_user_id", "environment", "user", ["owner_user_id"], ["id"]
    )

    _backfill(op.get_bind())

    op.alter_column("environment", "tier_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("environment", "environment_type")

    # Not `ix_environment_tier_id`: environment_tier's own primary key index is
    # already called that, and PostgreSQL index names are unique per schema.
    op.create_index("ix_environment_tier_fk", "environment", ["tier_id"])
    op.create_index("ix_environment_owner_user_id", "environment", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_environment_owner_user_id", table_name="environment")
    op.drop_index("ix_environment_tier_fk", table_name="environment")

    op.add_column(
        "environment", sa.Column("environment_type", sa.String(length=100), nullable=True)
    )
    # Truncate in the copy itself, not in a later statement: a tier name over
    # 100 characters (reachable — environment_tier.name is String(200) and the
    # tier API lets an admin create one) would otherwise fail this UPDATE
    # outright on PostgreSQL ("value too long for type character varying(100)"),
    # so a later truncating statement would never run.
    op.get_bind().execute(
        sa.text(
            "UPDATE environment SET environment_type = substr("
            "(SELECT name FROM environment_tier WHERE environment_tier.id = environment.tier_id)"
            ", 1, 100)"
        )
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE environment SET environment_type = 'unknown' "
            "WHERE environment_type IS NULL"
        )
    )
    op.alter_column(
        "environment", "environment_type", existing_type=sa.String(length=100), nullable=False
    )

    op.drop_constraint("fk_environment_owner_user_id", "environment", type_="foreignkey")
    op.drop_constraint("fk_environment_tier_id", "environment", type_="foreignkey")
    op.drop_column("environment", "expires_at")
    op.drop_column("environment", "owner_user_id")
    op.drop_column("environment", "tier_id")

    op.drop_index("ix_environment_tier_id", table_name="environment_tier")
    op.drop_index("ix_environment_tier_tenant_id", table_name="environment_tier")
    op.drop_table("environment_tier")
