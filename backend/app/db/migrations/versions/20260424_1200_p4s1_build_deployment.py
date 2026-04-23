"""phase 4 sub-1: api_key + build + deployment tables; ESSV rename + FK

Revision ID: p4s1builddeploy
Revises: p3s8gateduedate
Create Date: 2026-04-24 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p4s1builddeploy"
down_revision: Union[str, None] = "p3s8gateduedate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "api_key"):
        op.create_table(
            "api_key",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.UniqueConstraint("tenant_id", "key_hash", name="uq_api_key_tenant_hash"),
        )
        op.create_index("ix_api_key_tenant_id", "api_key", ["tenant_id"])
        op.create_index("ix_api_key_created_by", "api_key", ["created_by"])

    if not _table_exists(conn, "build"):
        op.create_table(
            "build",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("subsystem_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=True),
            sa.Column("git_sha", sa.String(64), nullable=False),
            sa.Column("git_branch", sa.String(255), nullable=True),
            sa.Column("build_number", sa.String(80), nullable=True),
            sa.Column("commit_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("build_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("build_finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("jira_tickets", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("pipeline_steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["subsystem_id"], ["subsystem.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "tenant_id", "subsystem_id", "git_sha", "build_number",
                name="uq_build_tenant_sub_sha_num",
            ),
        )
        op.create_index("ix_build_tenant_id", "build", ["tenant_id"])
        op.create_index("ix_build_subsystem_id", "build", ["subsystem_id"])
        op.create_index("ix_build_release_id", "build", ["release_id"])
        op.create_index("ix_build_tenant_subsystem", "build", ["tenant_id", "subsystem_id"])

    if not _table_exists(conn, "deployment"):
        op.create_table(
            "deployment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("build_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=True),
            sa.Column("change_request_id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.String(36), nullable=False),
            sa.Column("deployer_name", sa.String(255), nullable=True),
            sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["build_id"], ["build.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("tenant_id", "event_id", name="uq_deployment_tenant_event"),
        )
        op.create_index("ix_deployment_tenant_id", "deployment", ["tenant_id"])
        op.create_index("ix_deployment_build_id", "deployment", ["build_id"])
        op.create_index("ix_deployment_environment_id", "deployment", ["environment_id"])
        op.create_index("ix_deployment_release_id", "deployment", ["release_id"])
        op.create_index("ix_deployment_change_request_id", "deployment", ["change_request_id"])

    # ESSV changes — rename build_id → build_identifier, add build_fk_id FK.
    if _column_exists(conn, "environment_subsystem_version", "build_id"):
        op.alter_column("environment_subsystem_version", "build_id", new_column_name="build_identifier")
    if not _column_exists(conn, "environment_subsystem_version", "build_fk_id"):
        op.add_column(
            "environment_subsystem_version",
            sa.Column("build_fk_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_essv_build_fk", "environment_subsystem_version", "build",
            ["build_fk_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index(
            "ix_essv_build_fk_id", "environment_subsystem_version", ["build_fk_id"]
        )

    # Add is_system column to lifecycle_template if not present.
    if not _column_exists(conn, "lifecycle_template", "is_system"):
        op.add_column(
            "lifecycle_template",
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    # Per-tenant seed of the Code Deployment lifecycle template.
    # Idempotent: skip tenants where a template with the same
    # (tenant_id, entity_type, name) already exists.
    import json
    definition = json.dumps({
        "states": [
            {"key": "created", "label": "Created", "is_initial": True, "is_terminal": False},
            {"key": "deployed", "label": "Deployed", "is_initial": False, "is_terminal": True},
            {"key": "failed", "label": "Failed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from": "created", "to": "deployed", "roles": []},
            {"from": "created", "to": "failed", "roles": []},
        ],
        "field_permissions": {
            "created": {"standard_fields": {}, "custom_fields": {}},
            "deployed": {"standard_fields": {}, "custom_fields": {}},
            "failed": {"standard_fields": {}, "custom_fields": {}},
        },
    })
    op.execute(sa.text("""
        INSERT INTO lifecycle_template (
            tenant_id, entity_type, name, is_system, is_default, definition,
            created_at, updated_at
        )
        SELECT t.id, 'change_request', 'Code Deployment', true, false,
               CAST(:definition AS JSONB), now(), now()
        FROM tenant t
        WHERE NOT EXISTS (
            SELECT 1 FROM lifecycle_template lt
            WHERE lt.tenant_id = t.id
              AND lt.entity_type = 'change_request'
              AND lt.name = 'Code Deployment'
        )
    """).bindparams(definition=definition))


def downgrade() -> None:
    conn = op.get_bind()

    op.execute(sa.text("""
        DELETE FROM lifecycle_template
        WHERE entity_type = 'change_request' AND name = 'Code Deployment'
    """))

    if _column_exists(conn, "lifecycle_template", "is_system"):
        op.drop_column("lifecycle_template", "is_system")

    if _column_exists(conn, "environment_subsystem_version", "build_fk_id"):
        op.drop_index("ix_essv_build_fk_id", table_name="environment_subsystem_version")
        op.drop_constraint("fk_essv_build_fk", "environment_subsystem_version", type_="foreignkey")
        op.drop_column("environment_subsystem_version", "build_fk_id")

    # Drop the FK on build_identifier → build before dropping build table.
    insp = Inspector.from_engine(conn)
    essv_fks = {fk["name"] for fk in insp.get_foreign_keys("environment_subsystem_version")}
    if "fk_env_sub_version_build_id" in essv_fks:
        op.drop_constraint("fk_env_sub_version_build_id", "environment_subsystem_version", type_="foreignkey")

    if _column_exists(conn, "environment_subsystem_version", "build_identifier"):
        op.alter_column("environment_subsystem_version", "build_identifier", new_column_name="build_id")

    if _table_exists(conn, "deployment"):
        op.drop_table("deployment")
    if _table_exists(conn, "build"):
        op.drop_table("build")
    if _table_exists(conn, "api_key"):
        op.drop_table("api_key")
