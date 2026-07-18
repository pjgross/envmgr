from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, SmallInteger, Boolean, DateTime, JSON, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RaidItem(Base):
    __tablename__ = "raid_item"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # risk|assumption|issue|dependency
    seq: Mapped[int] = mapped_column(Integer, nullable=False)           # per (release_id, item_type)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # scoring (risk/issue)
    probability: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    impact: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    # risk
    response_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # avoid|reduce|transfer|accept
    mitigation_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contingency_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # assumption
    validation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # unvalidated|validated|invalidated
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # issue
    resolution_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # dependency
    direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # inbound|outbound
    counterparty: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    at_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    release_dependency_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release_dependency.id"), nullable=True)
    # promotion
    promoted_from_id: Mapped[Optional[int]] = mapped_column(ForeignKey("raid_item.id"), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RaidConfig(Base):
    __tablename__ = "raid_config"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True, unique=True)
    probability_scale: Mapped[list] = mapped_column(JSON, nullable=False)
    impact_scale: Mapped[list] = mapped_column(JSON, nullable=False)
    rag_bands: Mapped[list] = mapped_column(JSON, nullable=False)


class RaidItemScopeLink(Base):
    __tablename__ = "raid_item_scope_link"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    raid_item_id: Mapped[int] = mapped_column(ForeignKey("raid_item.id", ondelete="CASCADE"), nullable=False, index=True)
    release_change_id: Mapped[int] = mapped_column(ForeignKey("release_change.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("raid_item_id", "release_change_id", name="uq_raid_scope_link"),
    )


class RaidItemRelation(Base):
    __tablename__ = "raid_item_relation"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    from_item_id: Mapped[int] = mapped_column(ForeignKey("raid_item.id", ondelete="CASCADE"), nullable=False, index=True)
    to_item_id: Mapped[int] = mapped_column(ForeignKey("raid_item.id", ondelete="CASCADE"), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(20), nullable=False)  # relates_to|caused_by|duplicates|blocks

    __table_args__ = (
        UniqueConstraint("from_item_id", "to_item_id", "relation", name="uq_raid_relation"),
        CheckConstraint("from_item_id != to_item_id", name="ck_raid_relation_self"),
    )


class RaidItemHistory(Base):
    __tablename__ = "raid_item_history"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    raid_item_id: Mapped[int] = mapped_column(ForeignKey("raid_item.id", ondelete="CASCADE"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
