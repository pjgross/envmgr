"""B5 — one tenant's idle-detection and decommission-notice settings.

Shaped like EnvironmentNamingPolicy: tenant_id unique, no deleted_at, no DELETE
path. `idle_detection_enabled` is the off switch.
"""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentLifecyclePolicy(Base):
    __tablename__ = "environment_lifecycle_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    # DEFAULTS OFF. B2's ?governance_gap=true matched every environment on first
    # deploy and looked exactly like a bug; no tenant's estate should light up
    # with a flag they did not ask for.
    idle_detection_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    idle_threshold_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    # §2.12's five-day warning.
    decommission_notice_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
