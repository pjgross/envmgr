"""Move a PIR's free text into findings and actions, then drop the columns.

Revision ID: pirbackfill
Revises: pirfindings
Create Date: 2026-08-29 09:30:00.000000

`pir` kept five text columns and a single `incident_id`. A review that found six
things could not say which root cause belonged to which failure, and the link to
an incident was 1:1 in both directions. This moves each PIR's text into the
findings tables `pirfindings` created and then drops the columns.

Titles are FIXED STRINGS ("What went well (migrated)"), never a truncation of
the body: `pir_finding.title` is 500 characters and the free text is unbounded,
so slicing it in would silently lose the tail of a long review. The body goes to
`detail`, which is `Text` and has no cap.

A went_wrong finding is created if ANY of `what_went_wrong`, `root_cause`,
`action_plan` or `incident_id` held a value, so nothing is stranded by the
absence of one field. A PIR that only ever had a summary migrates to nothing,
and neither does one whose columns hold only whitespace — a blank finding is
worse than no finding, because someone has to read it to discover it says
nothing. Soft-deleted PIRs are skipped: a withdrawn review is not evidence.

`created_at`/`updated_at` are left to the tables' own server defaults rather
than written as `now()`, so this migration contains no dialect-specific SQL.

DOWNGRADE RE-ADDS THE FIVE COLUMNS AS NULLABLE AND DOES NOT RECONSTRUCT THE
TEXT. The findings rows survive a downgrade; the free text does not come back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'pirbackfill'
down_revision: Union[str, None] = 'pirfindings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(sa.text(
        "SELECT id, tenant_id, created_by, root_cause, what_went_well, what_went_wrong, "
        "action_plan, incident_id FROM pir WHERE deleted_at IS NULL ORDER BY id"
    )).mappings().all()

    insert_finding = sa.text(
        "INSERT INTO pir_finding (tenant_id, pir_id, kind, seq, title, detail, root_cause, "
        "created_by) "
        "VALUES (:tenant_id, :pir_id, :kind, 1, :title, :detail, :root_cause, :created_by) "
        "RETURNING id"
    )
    insert_action = sa.text(
        "INSERT INTO pir_action (tenant_id, finding_id, seq, title, detail, status, created_by) "
        "VALUES (:tenant_id, :finding_id, 1, :title, :detail, 'open', :created_by)"
    )
    insert_citation = sa.text(
        "INSERT INTO pir_finding_incident (tenant_id, finding_id, incident_id) "
        "VALUES (:tenant_id, :finding_id, :incident_id)"
    )

    def _has_text(value) -> bool:
        return value is not None and str(value).strip() != ""

    for row in rows:
        if _has_text(row["what_went_well"]):
            conn.execute(insert_finding, {
                "tenant_id": row["tenant_id"], "pir_id": row["id"], "kind": "went_well",
                "title": "What went well (migrated)", "detail": row["what_went_well"],
                "root_cause": None, "created_by": row["created_by"],
            })

        wrong_text = (
            _has_text(row["what_went_wrong"])
            or _has_text(row["root_cause"])
            or _has_text(row["action_plan"])
        )
        if not wrong_text and row["incident_id"] is None:
            continue

        finding_id = conn.execute(insert_finding, {
            "tenant_id": row["tenant_id"], "pir_id": row["id"], "kind": "went_wrong",
            # An incident-only PIR gets a title that says so, rather than
            # "What went wrong (migrated)" over an empty body.
            "title": "What went wrong (migrated)" if wrong_text else "Incident (migrated)",
            "detail": row["what_went_wrong"], "root_cause": row["root_cause"],
            "created_by": row["created_by"],
        }).scalar_one()

        if _has_text(row["action_plan"]):
            conn.execute(insert_action, {
                "tenant_id": row["tenant_id"], "finding_id": finding_id,
                "title": "Action plan (migrated)", "detail": row["action_plan"],
                "created_by": row["created_by"],
            })
        if row["incident_id"] is not None:
            conn.execute(insert_citation, {
                "tenant_id": row["tenant_id"], "finding_id": finding_id,
                "incident_id": row["incident_id"],
            })

    op.drop_index("ix_pir_tenant_incident", table_name="pir")
    op.drop_index("ix_pir_incident_id", table_name="pir")
    op.drop_column("pir", "incident_id")
    op.drop_column("pir", "root_cause")
    op.drop_column("pir", "what_went_well")
    op.drop_column("pir", "what_went_wrong")
    op.drop_column("pir", "action_plan")


def downgrade() -> None:
    op.add_column("pir", sa.Column("incident_id", sa.Integer(), nullable=True))
    op.add_column("pir", sa.Column("root_cause", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("what_went_well", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("what_went_wrong", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("action_plan", sa.Text(), nullable=True))
    op.create_foreign_key("fk_pir_incident_id", "pir", "incident", ["incident_id"], ["id"])
    op.create_index("ix_pir_incident_id", "pir", ["incident_id"])
    op.create_index("ix_pir_tenant_incident", "pir", ["tenant_id", "incident_id"])
