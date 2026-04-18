"""add_environment_subsystem_version

Revision ID: 2436af1aef0c
Revises: 0d99256c6a56
Create Date: 2026-03-23 14:30:39.251305

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2436af1aef0c'
down_revision: Union[str, None] = '0d99256c6a56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'environment_subsystem_version',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('environment_id', sa.Integer(), nullable=False),
        sa.Column('subsystem_id', sa.Integer(), nullable=False),
        sa.Column('build_id', sa.String(200), nullable=False),
        sa.Column('version_label', sa.String(200), nullable=False),
        sa.Column('installed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['environment_id'], ['environment.id']),
        sa.ForeignKeyConstraint(['subsystem_id'], ['subsystem.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_environment_subsystem_version_id', 'environment_subsystem_version', ['id'])
    op.create_index('ix_environment_subsystem_version_environment_id', 'environment_subsystem_version', ['environment_id'])
    op.create_index('ix_environment_subsystem_version_subsystem_id', 'environment_subsystem_version', ['subsystem_id'])
    op.create_index('ix_environment_subsystem_version_tenant_id', 'environment_subsystem_version', ['tenant_id'])
    op.create_index('ix_env_sub_version_lookup', 'environment_subsystem_version', ['environment_id', 'subsystem_id'])


def downgrade() -> None:
    op.drop_index('ix_env_sub_version_lookup', table_name='environment_subsystem_version')
    op.drop_index('ix_environment_subsystem_version_tenant_id', table_name='environment_subsystem_version')
    op.drop_index('ix_environment_subsystem_version_subsystem_id', table_name='environment_subsystem_version')
    op.drop_index('ix_environment_subsystem_version_environment_id', table_name='environment_subsystem_version')
    op.drop_index('ix_environment_subsystem_version_id', table_name='environment_subsystem_version')
    op.drop_table('environment_subsystem_version')
