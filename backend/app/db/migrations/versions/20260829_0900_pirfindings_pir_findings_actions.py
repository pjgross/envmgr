"""PIR findings, actions and incident citations — the three new tables.

Revision ID: pirfindings
Revises: rollbackgov
Create Date: 2026-08-29 09:00:00.000000

Additive only: three new tables, no change to any existing table and no
backfill. The follow-on revision `pirbackfill` moves the existing free text on
`pir` into these tables and then drops those columns; splitting the two keeps
the destructive half in its own revision, which can be reviewed and rehearsed
on a scratch database on its own.

See app/db/models/pir_finding.py for what each table records and why.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'pirfindings'
down_revision: Union[str, None] = 'rollbackgov'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pir_finding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("pir_id", sa.Integer(), sa.ForeignKey("pir.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # `Base` declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here a migration-built database
    # differs from a create_all-built one, and test_migration_schema_drift.py
    # (column NAME sets only) would not catch the difference.
    op.create_index("ix_pir_finding_id", "pir_finding", ["id"])
    op.create_index("ix_pir_finding_tenant_id", "pir_finding", ["tenant_id"])
    op.create_index("ix_pir_finding_pir_id", "pir_finding", ["pir_id"])
    op.create_index("ix_pir_finding_tenant_pir", "pir_finding", ["tenant_id", "pir_id"])

    op.create_table(
        "pir_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("finding_id", sa.Integer(),
                  sa.ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pir_action_id", "pir_action", ["id"])
    op.create_index("ix_pir_action_tenant_id", "pir_action", ["tenant_id"])
    op.create_index("ix_pir_action_finding_id", "pir_action", ["finding_id"])
    op.create_index("ix_pir_action_tenant_finding", "pir_action", ["tenant_id", "finding_id"])
    op.create_index("ix_pir_action_tenant_status", "pir_action", ["tenant_id", "status"])

    op.create_table(
        "pir_finding_incident",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("finding_id", sa.Integer(),
                  sa.ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("finding_id", "incident_id", name="uq_pir_finding_incident"),
    )
    op.create_index("ix_pir_finding_incident_id", "pir_finding_incident", ["id"])
    op.create_index("ix_pir_finding_incident_tenant_id", "pir_finding_incident", ["tenant_id"])
    op.create_index("ix_pir_finding_incident_finding_id", "pir_finding_incident", ["finding_id"])
    op.create_index("ix_pir_finding_incident_incident_id", "pir_finding_incident", ["incident_id"])
    op.create_index("ix_pir_finding_incident_tenant_incident", "pir_finding_incident",
                    ["tenant_id", "incident_id"])


def downgrade() -> None:
    op.drop_table("pir_finding_incident")
    op.drop_table("pir_action")
    op.drop_table("pir_finding")
