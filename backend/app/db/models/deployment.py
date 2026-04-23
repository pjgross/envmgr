from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Deployment(Base):
    __tablename__ = "deployment"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_deployment_tenant_event"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    build_id: Mapped[int] = mapped_column(
        ForeignKey("build.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_request.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    deployer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    custom_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
