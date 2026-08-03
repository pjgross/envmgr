"""Detector registry.

A detector is a name, a path predicate, and a parse function. Adding one is a
module plus an entry in DETECTORS: it cannot alter traversal, authentication
or rate-limit handling, because it never sees them — it receives only the
paths it claimed.
"""
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from app.db.models.dependency import DependencySource
from app.db.models.system import SubSystemSource
from app.services.scanning.declared import DeclaredState


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
    #: Fetch another file from the same repository. A Helm or Kustomize
    #: detector needs a companion file (values.yaml, an .env beside a compose
    #: file); without this it would have to own the walk.
    fetch: Callable[[str], Awaitable[Optional[bytes]]]


@dataclass(frozen=True)
class Detector:
    name: str
    matches: Callable[[str], bool]
    #: Pure: parses content into a value, touching no database. That is what
    #: lets one walk serve both the scan and the drift report.
    parse: Callable[[ParseContext], Awaitable[DeclaredState]]
    #: Provenance stamped on subsystems this detector declares, and the source
    #: whose catalogue rows it is compared against.
    subsystem_source: SubSystemSource
    #: The dependency source this detector owns, or None if it declares no
    #: edges. apply() deletes on this, so None means "never delete edges here".
    edge_source: DependencySource | None = None
