"""incident tables

Revision ID: 02355a0014b8
Revises: scopedeadline
Create Date: 2026-07-28 12:55:49.490763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02355a0014b8'
down_revision: Union[str, None] = 'scopedeadline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incident",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=2), nullable=False),
        sa.Column("lifecycle_template_id", sa.Integer(), sa.ForeignKey("lifecycle_template.id"), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployment.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=True),
        sa.Column("fix_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=True),
        sa.Column("subsystem_id", sa.Integer(), sa.ForeignKey("subsystem.id"), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incident_tenant_id", "incident", ["tenant_id"])
    op.create_index("ix_incident_tenant_status", "incident", ["tenant_id", "status"])
    op.create_index("ix_incident_tenant_release", "incident", ["tenant_id", "release_id"])
    op.create_index("ix_incident_tenant_system", "incident", ["tenant_id", "system_id"])
    op.create_index("ix_incident_tenant_source_ref", "incident", ["tenant_id", "source", "external_ref"])
    op.create_table(
        "incident_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_state", sa.String(length=50), nullable=True),
        sa.Column("to_state", sa.String(length=50), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_status_history_tenant_id", "incident_status_history", ["tenant_id"])
    op.create_index("ix_incident_status_history_incident_id", "incident_status_history", ["incident_id"])


def downgrade() -> None:
    op.drop_table("incident_status_history")
    op.drop_table("incident")
