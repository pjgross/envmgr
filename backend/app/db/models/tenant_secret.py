from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantSecret(Base):
    """A third-party credential held on a tenant's behalf, encrypted at rest.

    One row per (tenant, kind): reconnecting replaces rather than accumulating.
    `expires_at` exists for short-lived rows such as an in-flight OAuth device
    code, which is itself a credential and so shares this table's encryption
    rather than getting a second, parallel mechanism.
    """

    __tablename__ = "tenant_secret"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_tenant_secret_tenant_kind"),
    )

    def __repr__(self) -> str:
        # Never include ciphertext — reprs end up in logs.
        return f"<TenantSecret(tenant={self.tenant_id}, kind='{self.kind}')>"
