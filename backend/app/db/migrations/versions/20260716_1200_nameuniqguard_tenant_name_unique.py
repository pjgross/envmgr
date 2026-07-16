"""tenant-scoped name uniqueness guards for system, subsystem, environment

Name-based resolution (deployment webhook + can-deploy preflight) uses
scalar_one_or_none() on a name lookup. Without a uniqueness guard, two active
rows sharing a name make that raise MultipleResultsFound → HTTP 500. These
partial unique indexes make the ambiguity impossible at the DB level.

Natural keys:
  - system:      (tenant_id, name)   WHERE deleted_at IS NULL
  - subsystem:   (system_id, name)   WHERE deleted_at IS NULL  (system_id implies tenant;
                 matches deployment_service._resolve_subsystem, which scopes by system_id)
  - environment: (tenant_id, name)   WHERE deleted_at IS NULL

Partial (WHERE deleted_at IS NULL) so soft-deleted rows can share/reuse a name.

Postgres-only: SQLite (test DB) recreates the schema via Base.metadata each test
and is not migrated (same convention as p3s7memuniq).

Revision ID: nameuniqguard
Revises: p4s1builddeploy
Create Date: 2026-07-16 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "nameuniqguard"
down_revision: Union[str, None] = "p4s1builddeploy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index name, table, columns)
_INDEXES = [
    ("uq_system_tenant_name", "system", ["tenant_id", "name"]),
    ("uq_subsystem_system_name", "subsystem", ["system_id", "name"]),
    ("uq_environment_tenant_name", "environment", ["tenant_id", "name"]),
]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return  # SQLite test DB recreates schema via Base.metadata; no partial uniques
    for name, table, cols in _INDEXES:
        op.create_index(
            name, table, cols, unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for name, table, _cols in _INDEXES:
        try:
            op.drop_index(name, table_name=table)
        except Exception:
            pass
