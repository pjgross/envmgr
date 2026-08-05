"""Requests for environment access, or for a new environment.

Modelled on ChangeRequest: a `status` VARCHAR driven by a lifecycle_template,
so a tenant can add a review step by editing the template rather than needing
a schema change.

One table with a `kind` discriminator rather than two tables — the two modes
share the requester, justification, lifecycle, routing and Welcome Pack, and
differ in four fields. Mode-dependent requirements are enforced in the service,
where a violation can name the missing field; nullability here cannot explain
itself.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

REQUEST_KINDS = ("access", "new_environment")


class EnvironmentRequest(Base):
    __tablename__ = "environment_request"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
    lifecycle_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    needed_by: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # kind='access' — the environment being requested. Required by the service
    # for that kind; nullable here because the other kind has no target.
    environment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment.id"), nullable=True, index=True
    )

    # kind='new_environment' — what to build.
    proposed_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment_tier.id"), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Chosen by the approving Admin; becomes the created environment's team.
    operations_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Set on fulfilment. The audit link answering "where did this environment
    # come from?" — the question a manual-creation flow loses.
    created_environment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment.id"), nullable=True, index=True
    )

    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentRequest(id={self.id}, kind='{self.kind}', "
            f"status='{self.status}')>"
        )
