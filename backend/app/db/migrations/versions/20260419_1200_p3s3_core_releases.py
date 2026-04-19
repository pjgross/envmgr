"""phase 3 sub-project 1: core releases

Revision ID: p3s3releases
Revises: p3s2crmt
Create Date: 2026-04-19 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s3releases"
down_revision: Union[str, None] = "p3s2crmt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    # ── release_template ────────────────────────────────────────────────────
    if not _table_exists(conn, "release_template"):
        op.create_table(
            "release_template",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("release_type", sa.String(50), nullable=False),
            sa.Column("default_lifecycle_template_id", sa.Integer(), nullable=True),
            sa.Column("phases", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("gates", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["default_lifecycle_template_id"], ["lifecycle_template.id"]),
        )
        op.create_index("ix_release_template_tenant_id", "release_template", ["tenant_id"])

    # ── release ─────────────────────────────────────────────────────────────
    if not _table_exists(conn, "release"):
        op.create_table(
            "release",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(250), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("release_type", sa.String(50), nullable=False),
            sa.Column("release_kind", sa.String(20), nullable=False, server_default="project"),
            sa.Column("parent_release_id", sa.Integer(), nullable=True),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("lifecycle_template_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(100), nullable=False, server_default="draft"),
            sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("raised_by", sa.Integer(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["parent_release_id"], ["release.id"], name="fk_release_parent", use_alter=True),
            sa.ForeignKeyConstraint(["template_id"], ["release_template.id"], name="fk_release_template"),
            sa.ForeignKeyConstraint(["lifecycle_template_id"], ["lifecycle_template.id"]),
            sa.ForeignKeyConstraint(["raised_by"], ["user.id"]),
        )
        for idx, cols in [
            ("ix_release_tenant_id", ["tenant_id"]),
            ("ix_release_lifecycle_template_id", ["lifecycle_template_id"]),
            ("ix_release_raised_by", ["raised_by"]),
            ("ix_release_parent_release_id", ["parent_release_id"]),
        ]:
            op.create_index(idx, "release", cols)

    # ── release_status_history ──────────────────────────────────────────────
    if not _table_exists(conn, "release_status_history"):
        op.create_table(
            "release_status_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("from_state", sa.String(100), nullable=True),
            sa.Column("to_state", sa.String(100), nullable=False),
            sa.Column("changed_by", sa.Integer(), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"]),
            sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
        )
        op.create_index("ix_release_status_history_release_id", "release_status_history", ["release_id"])

    # ── test_phase ──────────────────────────────────────────────────────────
    if not _table_exists(conn, "test_phase"):
        op.create_table(
            "test_phase",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_test_phase_release_id", "test_phase", ["release_id"])
        op.create_index("ix_test_phase_tenant_id", "test_phase", ["tenant_id"])

    # ── release_gate ────────────────────────────────────────────────────────
    if not _table_exists(conn, "release_gate"):
        op.create_table(
            "release_gate",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("test_phase_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("acceptance_criteria", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("decided_by", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_phase_id"], ["test_phase.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["decided_by"], ["user.id"]),
        )
        op.create_index("ix_release_gate_release_id", "release_gate", ["release_id"])
        op.create_index("ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"])

    # ── release_system ──────────────────────────────────────────────────────
    if not _table_exists(conn, "release_system"):
        op.create_table(
            "release_system",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("system_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("deployment_date", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["system_id"], ["system.id"]),
            sa.UniqueConstraint("release_id", "system_id", name="uq_release_system"),
        )
        op.create_index("ix_release_system_release_id", "release_system", ["release_id"])

    # ── release_dependency ─────────────────────────────────────────────────
    if not _table_exists(conn, "release_dependency"):
        op.create_table(
            "release_dependency",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("depends_on_release_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="deploys_after"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("last_dependency_target_date", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["depends_on_release_id"], ["release.id"]),
            sa.UniqueConstraint("release_id", "depends_on_release_id", name="uq_release_dependency"),
            sa.CheckConstraint("release_id != depends_on_release_id", name="ck_release_dep_self"),
        )
        op.create_index("ix_release_dependency_release_id", "release_dependency", ["release_id"])

    # ── release_event_type ─────────────────────────────────────────────────
    if not _table_exists(conn, "release_event_type"):
        op.create_table(
            "release_event_type",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("display_color", sa.String(7), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        )
        op.create_index("ix_release_event_type_tenant_id", "release_event_type", ["tenant_id"])

    # ── release_event ──────────────────────────────────────────────────────
    if not _table_exists(conn, "release_event"):
        op.create_table(
            "release_event",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("event_type_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_by", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_type_id"], ["release_event_type.id"]),
            sa.ForeignKeyConstraint(["recorded_by"], ["user.id"]),
        )
        op.create_index("ix_release_event_release_id", "release_event", ["release_id"])

    # ── release_change ─────────────────────────────────────────────────────
    if not _table_exists(conn, "release_change"):
        op.create_table(
            "release_change",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("external_key", sa.String(50), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("change_kind", sa.String(20), nullable=False),
            sa.Column("external_status", sa.String(100), nullable=True),
            sa.Column("system_id", sa.Integer(), nullable=True),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("jira_project_config_id", sa.Integer(), nullable=True),
            sa.Column("epic_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["system_id"], ["system.id"]),
        )
        op.create_index("ix_release_change_release_id", "release_change", ["release_id"])
        op.create_index("ix_release_change_external_key", "release_change", ["external_key"])
        # Partial unique on (tenant_id, external_key) where external_key IS NOT NULL
        # Use a plain unique + app-enforcement on SQLite; Postgres supports the partial.
        dialect = conn.dialect.name
        if dialect == "postgresql":
            op.execute(
                "CREATE UNIQUE INDEX uq_release_change_tenant_external_key "
                "ON release_change (tenant_id, external_key) WHERE external_key IS NOT NULL"
            )

    # ── booking: promote release_id + test_phase_id to real FKs ────────────
    # Existing columns are bare integers; drop-and-recreate is unnecessary —
    # just add the FK constraints by name. SQLite doesn't support ALTER ADD
    # CONSTRAINT, but dev/prod is Postgres; tests skip migrations entirely.
    if conn.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_booking_release_id", "booking", "release",
            ["release_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_booking_test_phase_id", "booking", "test_phase",
            ["test_phase_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_change_request_release_id", "change_request", "release",
            ["release_id"], ["id"], ondelete="SET NULL",
        )

    # ── custom_field_definition: entity_subtype ────────────────────────────
    if not _column_exists(conn, "custom_field_definition", "entity_subtype"):
        op.add_column(
            "custom_field_definition",
            sa.Column("entity_subtype", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for name, table in [
            ("fk_booking_release_id", "booking"),
            ("fk_booking_test_phase_id", "booking"),
            ("fk_change_request_release_id", "change_request"),
        ]:
            op.drop_constraint(name, table, type_="foreignkey")
    if _column_exists(conn, "custom_field_definition", "entity_subtype"):
        op.drop_column("custom_field_definition", "entity_subtype")
    for table in [
        "release_change", "release_event", "release_event_type",
        "release_dependency", "release_system", "release_gate",
        "test_phase", "release_status_history", "release", "release_template",
    ]:
        if _table_exists(conn, table):
            op.drop_table(table)
