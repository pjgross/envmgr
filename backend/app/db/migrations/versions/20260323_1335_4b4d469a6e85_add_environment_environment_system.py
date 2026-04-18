"""add_environment_environment_system

Revision ID: 4b4d469a6e85
Revises: bdaf96c2f222
Create Date: 2026-03-23 13:35:37.361093

Tables 'environment' and 'environment_system' were created by init_db before
this migration was introduced. The upgrade function uses IF NOT EXISTS so the
migration is idempotent whether or not init_db has already run.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4b4d469a6e85'
down_revision: Union[str, None] = 'bdaf96c2f222'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: Using IF NOT EXISTS because init_db() in base.py calls create_all() on startup,
    # which pre-creates tables in the dev environment. In production, init_db() should be
    # replaced with running `alembic upgrade head`. This pattern is used throughout Phase 1
    # and should be resolved before production deployment.
    conn = op.get_bind()

    # Create environment table if it doesn't already exist
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS environment (
            id SERIAL NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            environment_type VARCHAR(100) NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'active',
            tenant_id INTEGER NOT NULL REFERENCES tenant(id),
            custom_fields JSON,
            deleted_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_id ON environment (id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_tenant_id ON environment (tenant_id)"
    ))

    # Create environment_system table if it doesn't already exist
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS environment_system (
            id SERIAL NOT NULL,
            environment_id INTEGER NOT NULL REFERENCES environment(id),
            system_id INTEGER NOT NULL REFERENCES system(id),
            tenant_id INTEGER NOT NULL REFERENCES tenant(id),
            status VARCHAR NOT NULL DEFAULT 'active',
            mock_notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            CONSTRAINT uq_env_system UNIQUE (environment_id, system_id)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_system_id ON environment_system (id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_system_environment_id ON environment_system (environment_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_system_system_id ON environment_system (system_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_environment_system_tenant_id ON environment_system (tenant_id)"
    ))


def downgrade() -> None:
    op.drop_table('environment_system')
    op.drop_table('environment')
