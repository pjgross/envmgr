"""add missing created_at/updated_at columns inherited from Base

Six tables were created by migrations that omitted the ``created_at`` /
``updated_at`` columns every model inherits from ``Base``. Dev and test
databases are built by ``Base.metadata.create_all``, which supplies the
columns, so the gap only surfaced on a database built purely from the
migration chain — where any query against these tables fails with
``column "created_at" does not exist``.

The adds are conditional: databases bootstrapped via ``create_all`` already
have the columns and must not error here.

Revision ID: basetimestamps
Revises: 7441806378e5
Create Date: 2026-07-29 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'basetimestamps'
down_revision: Union[str, None] = '7441806378e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "component_dependency",
    "environment_health_status",
    "incident",
    "incident_status_history",
    "pir",
    "system_dependency",
)

COLUMNS = ("created_at", "updated_at")


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    for table in TABLES:
        present = _existing_columns(table)
        for column in COLUMNS:
            if column in present:
                continue
            op.add_column(
                table,
                sa.Column(
                    column,
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
            )


def downgrade() -> None:
    for table in TABLES:
        present = _existing_columns(table)
        for column in COLUMNS:
            if column in present:
                op.drop_column(table, column)
