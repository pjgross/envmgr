from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentHealthStatus(Base):
    __tablename__ = "environment_health_status"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # up | down | issue
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_env_health_tenant_env_recorded", "tenant_id", "environment_id", "recorded_at"),
    )
