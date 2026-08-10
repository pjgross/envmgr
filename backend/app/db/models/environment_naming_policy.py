from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentNamingPolicy(Base):
    """B2 — one tenant's naming and tagging convention. One row per tenant.

    Shaped like `RaidConfig`, this codebase's existing per-tenant config table:
    `tenant_id` unique, no `deleted_at`. There is no DELETE path — `is_enabled`
    is the off switch, and deleting the row would throw away the pattern.
    """

    __tablename__ = "environment_naming_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Null means "no naming rule, attributes only". Capped at 500 characters as
    # the first line of the ReDoS guard — see environment_compliance_service.
    name_pattern: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # A worked example, shown in the admin UI AND in the 422. Refused at save
    # if its own pattern rejects it, or the error message teaches a name that
    # will also be refused.
    name_pattern_example: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    # Vocabulary: 'owner', 'expiry', 'operations_group', and 'cf:<field_key>'.
    # 'tier' is deliberately NOT offered: environment.tier_id is already
    # nullable=False, so requiring it would be a check that can never fail — a
    # permanently-green row that reads as governance.
    required_attributes: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # Bumped whenever `name_pattern` or `required_attributes` changes, in EITHER
    # direction — "stricter" is not a decidable property of a regex change, and
    # granting fresh grace for a relaxation is harmless. NOT bumped by an edit
    # to grace_days, is_enabled or the example: those do not change what is
    # being asked of an environment.
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentNamingPolicy(tenant_id={self.tenant_id}, "
            f"enabled={self.is_enabled})>"
        )
