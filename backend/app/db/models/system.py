from sqlalchemy import String, Text, JSON, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime

from app.db.base import Base


class System(Base):
    """System model — a logical grouping of subsystems within a tenant."""

    __tablename__ = "system"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    github_repository_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    subsystems: Mapped[list["SubSystem"]] = relationship(
        "SubSystem", back_populates="system", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<System(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class SubSystem(Base):
    """SubSystem model — a component within a System."""

    __tablename__ = "subsystem"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    system: Mapped["System"] = relationship("System", back_populates="subsystems")

    def __repr__(self) -> str:
        return f"<SubSystem(id={self.id}, name='{self.name}', system_id={self.system_id})>"
