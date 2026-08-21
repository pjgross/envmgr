"""gate types, evidence and waivers

Revision ID: gatetypes
Revises: envdecommission
Create Date: 2026-08-20 18:29:54.627483

"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'gatetypes'
down_revision: Union[str, None] = 'envdecommission'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A literal copy of app.services.gate_type_defaults.STANDARD_GATE_TYPES,
# deliberately not an import: a migration reproduces the past and must not
# change meaning when that module gains a ninth type.
_STANDARD_GATE_TYPES = [
    {"name": "Functional",     "category": "functional",     "failure_behaviour": "block",
     "expected_evidence": ["Test execution report", "Defect summary"],
     "requires_deployment_link": True,  "display_order": 10},
    {"name": "NFR / Performance", "category": "nfr",         "failure_behaviour": "block",
     "expected_evidence": ["Performance test report"],
     "requires_deployment_link": True,  "display_order": 20},
    {"name": "Integration",    "category": "integration",    "failure_behaviour": "block",
     "expected_evidence": ["Integration test report"],
     "requires_deployment_link": True,  "display_order": 30},
    {"name": "Security",       "category": "security",       "failure_behaviour": "block",
     "expected_evidence": ["Security scan result"],
     "requires_deployment_link": True,  "display_order": 40},
    {"name": "License",        "category": "license",        "failure_behaviour": "warn",
     "expected_evidence": ["Dependency licence report"],
     "requires_deployment_link": False, "display_order": 50},
    {"name": "Accessibility",  "category": "accessibility",  "failure_behaviour": "warn",
     "expected_evidence": ["Accessibility audit"],
     "requires_deployment_link": False, "display_order": 60},
    {"name": "Business",       "category": "business",       "failure_behaviour": "accept_with_exception",
     "expected_evidence": ["Business sign-off"],
     "requires_deployment_link": False, "display_order": 70},
    {"name": "Ops Readiness",  "category": "ops_readiness",  "failure_behaviour": "block",
     "expected_evidence": ["Runbook", "Monitoring confirmation"],
     "requires_deployment_link": False, "display_order": 80},
]


def upgrade() -> None:
    op.create_table(
        "gate_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("failure_behaviour", sa.String(30), nullable=False, server_default="warn"),
        sa.Column("expected_evidence", sa.JSON(), nullable=False),
        sa.Column("requires_deployment_link", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gate_type_tenant_id", "gate_type", ["tenant_id"])
    # Base declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here, a migration-built database
    # differs from a create_all-built one — not caught by
    # test_migration_schema_drift.py, which compares only tables and columns.
    op.create_index("ix_gate_type_id", "gate_type", ["id"])

    op.create_table(
        "gate_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "gate_id", sa.Integer(),
            sa.ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(150), nullable=False),
        sa.Column("label", sa.String(250), nullable=False),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployment.id"), nullable=True),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gate_evidence_tenant_id", "gate_evidence", ["tenant_id"])
    op.create_index("ix_gate_evidence_gate_id", "gate_evidence", ["gate_id"])
    op.create_index("ix_gate_evidence_deployment_id", "gate_evidence", ["deployment_id"])
    op.create_index("ix_gate_evidence_id", "gate_evidence", ["id"])

    op.create_table(
        "gate_waiver",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "gate_id", sa.Integer(),
            sa.ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gate_waiver_tenant_id", "gate_waiver", ["tenant_id"])
    op.create_index("ix_gate_waiver_gate_id", "gate_waiver", ["gate_id"])
    op.create_index("ix_gate_waiver_id", "gate_waiver", ["id"])

    op.add_column(
        "release_gate",
        sa.Column("gate_type_id", sa.Integer(), sa.ForeignKey("gate_type.id"), nullable=True),
    )
    op.add_column(
        "release_gate",
        sa.Column("test_phase_id", sa.Integer(), sa.ForeignKey("test_phase.id"), nullable=True),
    )
    op.create_index("ix_release_gate_gate_type_id", "release_gate", ["gate_type_id"])
    op.create_index("ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"])

    # Backfill the eight types for every EXISTING tenant. Without this a tenant
    # has no vocabulary to type a gate with and the feature reads as broken
    # rather than unconfigured.
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant")).fetchall()]
    gate_type = sa.table(
        "gate_type",
        sa.column("tenant_id"), sa.column("name"), sa.column("category"),
        sa.column("failure_behaviour"), sa.column("expected_evidence"),
        sa.column("requires_deployment_link"), sa.column("display_order"),
        sa.column("is_active"), sa.column("created_at"), sa.column("updated_at"),
    )
    for tenant_id in tenant_ids:
        existing = {
            r[0].lower()
            for r in conn.execute(
                sa.text("SELECT name FROM gate_type WHERE tenant_id = :t"), {"t": tenant_id}
            ).fetchall()
        }
        rows = [
            {**spec, "tenant_id": tenant_id, "is_active": True,
             "created_at": now, "updated_at": now,
             "expected_evidence": json.dumps(spec["expected_evidence"])}
            for spec in _STANDARD_GATE_TYPES
            if spec["name"].lower() not in existing
        ]
        if rows:
            op.bulk_insert(gate_type, rows)


def downgrade() -> None:
    op.drop_index("ix_release_gate_test_phase_id", table_name="release_gate")
    op.drop_index("ix_release_gate_gate_type_id", table_name="release_gate")
    op.drop_column("release_gate", "test_phase_id")
    op.drop_column("release_gate", "gate_type_id")

    op.drop_index("ix_gate_waiver_id", table_name="gate_waiver")
    op.drop_index("ix_gate_waiver_gate_id", table_name="gate_waiver")
    op.drop_index("ix_gate_waiver_tenant_id", table_name="gate_waiver")
    op.drop_table("gate_waiver")

    op.drop_index("ix_gate_evidence_id", table_name="gate_evidence")
    op.drop_index("ix_gate_evidence_deployment_id", table_name="gate_evidence")
    op.drop_index("ix_gate_evidence_gate_id", table_name="gate_evidence")
    op.drop_index("ix_gate_evidence_tenant_id", table_name="gate_evidence")
    op.drop_table("gate_evidence")

    op.drop_index("ix_gate_type_id", table_name="gate_type")
    op.drop_index("ix_gate_type_tenant_id", table_name="gate_type")
    op.drop_table("gate_type")
