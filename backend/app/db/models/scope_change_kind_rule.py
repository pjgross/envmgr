"""Per-tenant admin config: which change_kind values count as scope changes.

Rows are lazily materialised at tenant creation (four standard kinds). Admins
toggle `counts_as_scope_change` via the tenant admin page. When evaluating
whether a scope-change release event should fire, the service reads this table
and short-circuits when the relevant kind's rule is false.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScopeChangeKindRule(Base):
    __tablename__ = "scope_change_kind_rule"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    counts_as_scope_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
