"""A4: project priority rank, and the contention escalation record

Revision ID: contention
Revises: relidx
Create Date: 2026-08-09

Two schema changes, one revision, because they are one sub-project and a single
head is easier to reason about than two.

`project.priority_rank` is nullable with NO BACKFILL, deliberately: unranked is
a real state and A4 reports an unranked pair as "priority does not separate
these" rather than picking a winner.

`contention_escalation` stores only the ASKING and the ANSWER. The verdict is
computed on read, and the escalation's own state (open/answered/expired) is
computed from `respond_by` and `decided_at` — there is no status column and
nothing to run on a schedule.
"""
import sqlalchemy as sa
from alembic import op

revision = "contention"
down_revision = "relidx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project", sa.Column("priority_rank", sa.Integer(), nullable=True))

    op.create_table(
        "contention_escalation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        # NORMALISED: booking_id < other_booking_id. A conflict is symmetric, so
        # (A,B) and (B,A) are one contention; without normalisation both owners
        # escalating the same clash create two records, two owners and two clocks.
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=False),
        sa.Column("other_booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=False),
        sa.Column("escalated_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        # Required: an escalation with no deadline can never expire, which would
        # remove the half of §2.12 that makes escalation time-bound.
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision_yields_booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=True
        ),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # `booking.id` is globally unique, so the pair alone is correct without
        # tenant_id — and leaving it out is what makes a second row impossible
        # rather than merely unlikely.
        sa.UniqueConstraint("booking_id", "other_booking_id", name="uq_contention_pair"),
    )
    op.create_index("ix_contention_escalation_id", "contention_escalation", ["id"])
    op.create_index("ix_contention_escalation_tenant_id", "contention_escalation", ["tenant_id"])
    op.create_index("ix_contention_escalation_booking_id", "contention_escalation", ["booking_id"])
    op.create_index(
        "ix_contention_escalation_other_booking_id", "contention_escalation", ["other_booking_id"]
    )
    op.create_index(
        "ix_contention_escalation_owner_user_id", "contention_escalation", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_table("contention_escalation")
    op.drop_column("project", "priority_rank")
