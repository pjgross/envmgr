"""add component_type technology label

Revision ID: 629381d81e87
Revises: b303ad51d0be
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = '629381d81e87'
down_revision = '78916e9c70e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('subsystem', sa.Column('component_type', sa.String(), nullable=False, server_default='other'))
    op.add_column('subsystem', sa.Column('technology', sa.String(100), nullable=True))
    op.add_column('system_dependency', sa.Column('label', sa.String(100), nullable=True))
    op.add_column('component_dependency', sa.Column('label', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('component_dependency', 'label')
    op.drop_column('system_dependency', 'label')
    op.drop_column('subsystem', 'technology')
    op.drop_column('subsystem', 'component_type')
