from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentOperatingHours(Base):
    """Per-environment weekly operating hours + IANA timezone (one row per env).

    `week` is a list of exactly 7 entries indexed by weekday (0=Mon..6=Sun), each
    {"closed": bool, "open": "HH:MM", "close": "HH:MM"}. Absence of a row means the
    environment has no operating hours configured.
    """
    __tablename__ = "environment_operating_hours"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    week: Mapped[list] = mapped_column(JSON, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("environment_id", name="uq_env_operating_hours_env"),
    )
