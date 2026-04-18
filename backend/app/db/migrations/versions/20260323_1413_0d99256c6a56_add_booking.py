"""add_booking

Revision ID: 0d99256c6a56
Revises: 408f62e493b5
Create Date: 2026-03-23 14:13:46.661692

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d99256c6a56'
down_revision: Union[str, None] = '408f62e493b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'booking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('environment_id', sa.Integer(), nullable=False),
        sa.Column('environment_group_id', sa.Integer(), nullable=True),
        sa.Column('project_name', sa.String(200), nullable=False),
        sa.Column('booked_by', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('booking_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recurrence_rule', sa.String(500), nullable=True),
        sa.Column('recurrence_parent_id', sa.Integer(), nullable=True),
        sa.Column('release_id', sa.Integer(), nullable=True),
        sa.Column('test_phase_id', sa.Integer(), nullable=True),
        sa.Column('context_tag', sa.String(), server_default=sa.text("'none'"), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['environment_id'], ['environment.id']),
        sa.ForeignKeyConstraint(['booked_by'], ['user.id']),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_booking_id', 'booking', ['id'])
    op.create_index('ix_booking_environment_id', 'booking', ['environment_id'])
    op.create_index('ix_booking_booked_by', 'booking', ['booked_by'])
    op.create_index('ix_booking_recurrence_parent_id', 'booking', ['recurrence_parent_id'])
    op.create_index('ix_booking_tenant_id', 'booking', ['tenant_id'])
    # Add self-referential FK separately (use_alter=True pattern)
    op.create_foreign_key(
        'fk_booking_parent', 'booking', 'booking',
        ['recurrence_parent_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_booking_parent', 'booking', type_='foreignkey')
    op.drop_index('ix_booking_tenant_id', table_name='booking')
    op.drop_index('ix_booking_recurrence_parent_id', table_name='booking')
    op.drop_index('ix_booking_booked_by', table_name='booking')
    op.drop_index('ix_booking_environment_id', table_name='booking')
    op.drop_index('ix_booking_id', table_name='booking')
    op.drop_table('booking')
