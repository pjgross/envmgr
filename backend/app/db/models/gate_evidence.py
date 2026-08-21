from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateEvidence(Base):
    """A reference vouching for a gate. NOT an artefact — this application has
    no file storage, so evidence is a URL plus an attestation of who added it.

    `deployment_id` is what makes it worth more than a bookmark: a deployment
    already pins which build of which subsystem landed in which environment and
    when, so evidence naming one inherits all of it — and becomes STALE when a
    later successful deployment of the same component supersedes it.
    """

    __tablename__ = "gate_evidence"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Free text, not an FK. The UI offers the type's expected_evidence entries
    # as choices; an unlisted kind is accepted and simply satisfies no
    # expectation.
    kind: Mapped[str] = mapped_column(String(150), nullable=False)
    label: Mapped[str] = mapped_column(String(250), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deployment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deployment.id"), nullable=True, index=True
    )
    added_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
