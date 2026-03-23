"""add_system_subsystem

Revision ID: bdaf96c2f222
Revises: ff40b07fafab
Create Date: 2026-03-23 13:13:58.113716

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bdaf96c2f222'
down_revision: Union[str, None] = 'ff40b07fafab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('github_repository_url', sa.String(length=500), nullable=True),
        sa.Column('custom_fields', sa.JSON(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_system_id', 'system', ['id'])
    op.create_index('ix_system_tenant_id', 'system', ['tenant_id'])

    op.create_table(
        'subsystem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('system_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('custom_fields', sa.JSON(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['system_id'], ['system.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_subsystem_id', 'subsystem', ['id'])
    op.create_index('ix_subsystem_system_id', 'subsystem', ['system_id'])
    op.create_index('ix_subsystem_tenant_id', 'subsystem', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_subsystem_tenant_id', table_name='subsystem')
    op.drop_index('ix_subsystem_system_id', table_name='subsystem')
    op.drop_index('ix_subsystem_id', table_name='subsystem')
    op.drop_table('subsystem')

    op.drop_index('ix_system_tenant_id', table_name='system')
    op.drop_index('ix_system_id', table_name='system')
    op.drop_table('system')
