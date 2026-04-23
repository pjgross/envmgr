from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKey(Base):
    __tablename__ = "api_key"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_hash", name="uq_api_key_tenant_hash"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
