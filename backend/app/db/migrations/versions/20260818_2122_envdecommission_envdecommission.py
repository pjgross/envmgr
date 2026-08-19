"""Phase 7 B5 — decommissioning workflow and idle detection.

ADDITIVE ONLY: four new tables, one nullable column on environment_tier, and a
seed of the two standard decommission steps for existing tenants. No backfill,
no data migration, nothing existing is rewritten.

The step seed is carried here as a LITERAL rather than imported from
environment_decommission_defaults: a migration reproduces the past, so it must
not change meaning when that module gains a third step. B3b's `envrequests`
recorded the deploy failure this prevents — a tenant that cannot complete the
workflow at all because its vocabulary was never seeded.

Revision ID: envdecommission
Revises: aabc21374208
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "envdecommission"
down_revision: Union[str, None] = "aabc21374208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_STEPS = [
    ("final_backup", "Final backup taken",
     "Record the snapshot id or backup job reference.", 10),
    ("teardown", "Infrastructure torn down",
     "Record the ticket or runbook run that removed it.", 20),
]


def upgrade() -> None:
    op.create_table(
        "environment_decommission",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_teardown_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initiated_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("extension_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_requested_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("extension_reason", sa.Text(), nullable=True),
        sa.Column("extension_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("extension_granted", sa.Boolean(), nullable=True),
        sa.Column("torn_down_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("torn_down_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_environment_decommission_tenant_id", "environment_decommission", ["tenant_id"])
    op.create_index("ix_environment_decommission_environment_id", "environment_decommission", ["environment_id"])

    op.create_table(
        "environment_decommission_attestation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("decommission_id", sa.Integer(),
                  sa.ForeignKey("environment_decommission.id"), nullable=False),
        sa.Column("step_key", sa.String(length=100), nullable=False),
        sa.Column("signed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("decommission_id", "step_key", name="uq_decommission_step"),
    )
    op.create_index("ix_environment_decommission_attestation_tenant_id",
                    "environment_decommission_attestation", ["tenant_id"])
    op.create_index("ix_environment_decommission_attestation_decommission_id",
                    "environment_decommission_attestation", ["decommission_id"])

    op.create_table(
        "environment_decommission_step",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_environment_decommission_step_tenant_id",
                    "environment_decommission_step", ["tenant_id"])

    op.create_table(
        "environment_lifecycle_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"),
                  nullable=False, unique=True),
        sa.Column("idle_detection_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("idle_threshold_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("decommission_notice_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_environment_lifecycle_policy_tenant_id",
                    "environment_lifecycle_policy", ["tenant_id"])

    op.add_column(
        "environment_tier",
        sa.Column("idle_threshold_days", sa.Integer(), nullable=True),
    )

    # Seed the step vocabulary for every EXISTING tenant. Without this a tenant
    # provisioned before B5 can never complete a teardown.
    conn = op.get_bind()
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenant"))]
    for tenant_id in tenant_ids:
        for key, label, description, order in _SEED_STEPS:
            conn.execute(
                sa.text(
                    "INSERT INTO environment_decommission_step "
                    "(tenant_id, key, label, description, display_order, "
                    " is_required, is_active, created_at, updated_at) "
                    "VALUES (:t, :k, :l, :d, :o, TRUE, TRUE, "
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"t": tenant_id, "k": key, "l": label, "d": description, "o": order},
            )


def downgrade() -> None:
    op.drop_column("environment_tier", "idle_threshold_days")
    op.drop_table("environment_lifecycle_policy")
    op.drop_table("environment_decommission_step")
    op.drop_table("environment_decommission_attestation")
    op.drop_table("environment_decommission")
