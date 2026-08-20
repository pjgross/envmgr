from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateType(Base):
    """Tenant-scoped release-gate type vocabulary.

    Shaped like EnvironmentTier, which B1 introduced for the same reason: a
    standard vocabulary that real tenants do not quite match. `category` maps a
    tenant's own name onto one of the eight standard types and is NULL for a
    type that matches none of them. A plain VARCHAR, not SAEnum — SAEnum stores
    the member NAME, which is why environment.status holds 'ACTIVE'.
    """

    __tablename__ = "gate_type"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # block | warn | accept_with_exception. Declares how a FAILURE READS in the
    # verdict — it never refuses anything. See the spec, section 2.
    failure_behaviour: Mapped[str] = mapped_column(String(30), nullable=False, default="warn")
    # JSON list of evidence KIND NAMES this type expects, e.g.
    # ["Test execution report", "Defect summary"]. Empty means none expected.
    # This is where the SIT -> UAT -> PreProd -> Production strictness ladder
    # lives: a "UAT Sign-off" type expects more kinds than a "SIT Sign-off".
    expected_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requires_deployment_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
