from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseDependency(Base):
    __tablename__ = "release_dependency"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="deploys_after")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_dependency_target_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("release_id", "depends_on_release_id", name="uq_release_dependency"),
        CheckConstraint("release_id != depends_on_release_id", name="ck_release_dep_self"),
    )
