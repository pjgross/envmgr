"""Detector registry.

A detector is a name, a path predicate, and a parse function. Adding one is a
module plus an entry in DETECTORS: it cannot alter traversal, authentication
or rate-limit handling, because it never sees them — it receives only the
paths it claimed.
"""
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class DetectorResult:
    subsystems_created: int = 0
    subsystems_updated: int = 0
    dependencies_written: int = 0
    warnings: list[str] = field(default_factory=list)

    def __add__(self, other: "DetectorResult") -> "DetectorResult":
        return DetectorResult(
            subsystems_created=self.subsystems_created + other.subsystems_created,
            subsystems_updated=self.subsystems_updated + other.subsystems_updated,
            dependencies_written=self.dependencies_written + other.dependencies_written,
            warnings=[*self.warnings, *other.warnings],
        )


@dataclass(frozen=True)
class ParseContext:
    content: bytes
    path: str
    system_id: int
    tenant_id: int
    db: AsyncSession
    #: Fetch another file from the same repository. A Helm or Kustomize
    #: detector needs a companion file (values.yaml, an .env beside a compose
    #: file); without this it would have to own the walk.
    fetch: Callable[[str], Awaitable[Optional[bytes]]]


@dataclass(frozen=True)
class Detector:
    name: str
    matches: Callable[[str], bool]
    parse: Callable[[ParseContext], Awaitable[DetectorResult]]
