"""closeout hypercare and closeout

Revision ID: closeout
Revises: gonogo
Create Date: 2026-09-09 10:00:00

Five nullable columns on `release`, `test_phase.kind`, then two data steps:
flag the three deployed terminal states of every existing PROJECT release
template (by state KEY — a renamed key gets nothing and the closeout tab
says so), and seed four system release event types per tenant. Neither
inserts a state or a transition into any template.
"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'closeout'
down_revision: Union[str, None] = 'gonogo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_FLAGS = ("marks_deployed", "is_closed", "requires_pir_complete", "requires_handover_confirmed")

# A literal copy, never an import from release_defaults: the migration must
# reproduce what was seeded on 2026-09-09 even after the module changes.
_EVENT_TYPES = [
    ("Declared stable", "#2e7d32"),
    ("Stability declaration withdrawn", "#ed6c02"),
    ("Ops handover confirmed", "#1976d2"),
    ("Ops handover withdrawn", "#ed6c02"),
]

_PROJECT_RELEASE_TEMPLATES = sa.text(
    "SELECT id, definition FROM lifecycle_template "
    "WHERE entity_type = 'release' "
    "AND (applies_to_kind IS NULL OR applies_to_kind <> 'enterprise')"
)
_UPDATE_DEFINITION = sa.text(
    "UPDATE lifecycle_template SET definition = :d WHERE id = :i"
).bindparams(sa.bindparam("d", type_=sa.JSON()))


def _load(raw):
    return raw if isinstance(raw, dict) else json.loads(raw)


def upgrade() -> None:
    op.add_column("release", sa.Column("operations_group_id", sa.Integer(),
                                       sa.ForeignKey("user_group.id"), nullable=True))
    op.create_index("ix_release_operations_group_id", "release", ["operations_group_id"])
    op.add_column("release", sa.Column("declared_stable_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("release", sa.Column("declared_stable_by", sa.Integer(),
                                       sa.ForeignKey("user.id"), nullable=True))
    op.add_column("release", sa.Column("handover_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("release", sa.Column("handover_confirmed_by", sa.Integer(),
                                       sa.ForeignKey("user.id"), nullable=True))
    op.add_column("test_phase", sa.Column("kind", sa.String(20), nullable=False, server_default="test"))

    conn = op.get_bind()
    for tid, raw in conn.execute(_PROJECT_RELEASE_TEMPLATES).fetchall():
        defn = _load(raw)
        changed = False
        for s in defn.get("states", []):
            if s.get("key") in ("completed", "completed_with_issues"):
                s["marks_deployed"] = True
                s["is_closed"] = True
                changed = True
            elif s.get("key") == "backed_out":
                s["is_closed"] = True
                changed = True
        if changed:
            conn.execute(_UPDATE_DEFINITION, {"d": defn, "i": tid})

    now = datetime.now(timezone.utc)
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant")).fetchall()]
    for tenant_id in tenant_ids:
        existing = {r[0] for r in conn.execute(
            sa.text("SELECT name FROM release_event_type WHERE tenant_id = :t AND is_system = :s"),
            {"t": tenant_id, "s": True}).fetchall()}
        for name, color in _EVENT_TYPES:
            if name in existing:
                continue
            conn.execute(sa.text(
                "INSERT INTO release_event_type (tenant_id, name, display_color, is_system, "
                "created_at, updated_at) VALUES (:t, :n, :c, :s, :now, :now)"),
                {"t": tenant_id, "n": name, "c": color, "s": True, "now": now})


def downgrade() -> None:
    conn = op.get_bind()
    for tid, raw in conn.execute(sa.text(
            "SELECT id, definition FROM lifecycle_template WHERE entity_type = 'release'")).fetchall():
        defn = _load(raw)
        changed = False
        for s in defn.get("states", []):
            for flag in NEW_FLAGS:
                if flag in s:
                    s.pop(flag)
                    changed = True
        if changed:
            conn.execute(_UPDATE_DEFINITION, {"d": defn, "i": tid})
    # The four event types are left in place: a release event may reference them.
    op.drop_column("test_phase", "kind")
    op.drop_column("release", "handover_confirmed_by")
    op.drop_column("release", "handover_confirmed_at")
    op.drop_column("release", "declared_stable_by")
    op.drop_column("release", "declared_stable_at")
    op.drop_index("ix_release_operations_group_id", table_name="release")
    op.drop_column("release", "operations_group_id")
