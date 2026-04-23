from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EnvironmentSubSystemVersion(Base):
    __tablename__ = "environment_subsystem_version"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    build_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    build_fk_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("build.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version_label: Mapped[str] = mapped_column(String(200), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    environment: Mapped["Environment"] = relationship("Environment")  # type: ignore[name-defined]
    subsystem: Mapped["SubSystem"] = relationship("SubSystem")  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_env_sub_version_lookup", "environment_id", "subsystem_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSubSystemVersion(id={self.id}, env={self.environment_id}, "
            f"sub={self.subsystem_id}, version='{self.version_label}')>"
        )
