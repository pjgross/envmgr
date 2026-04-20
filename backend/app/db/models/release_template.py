from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseTemplate(Base):
    __tablename__ = "release_template"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_lifecycle_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=True
    )
    phases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
