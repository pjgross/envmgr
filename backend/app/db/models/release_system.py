from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseSystem(Base):
    __tablename__ = "release_system"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    deployment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("release_id", "system_id", name="uq_release_system"),
    )
