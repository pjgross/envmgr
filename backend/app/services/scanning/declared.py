"""What a repository declares, expressed as a value.

Detectors parse into these. `reconcile.apply` writes them and `reconcile.diff`
compares them against the catalogue — both reading the same value, which is
what stops a drift report describing a change a scan would not make.

Nothing here touches the database. That is the point: it is what makes the
parsers testable without one.

Values are canonical as emitted. Parsers truncate `name` to 200, `technology`
to 100 and `source_path` to 500 characters, matching the column widths, so
that a stored row compares equal to the declaration it came from. Truncating
in `apply()` instead would make `diff()` report a change on every run.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeclaredSubsystem:
    name: str
    component_type: str
    technology: str | None
    source_path: str


@dataclass(frozen=True)
class DeclaredEdge:
    from_name: str
    to_name: str
    port: int | None
    source_path: str


@dataclass
class DeclaredState:
    subsystems: list[DeclaredSubsystem] = field(default_factory=list)
    edges: list[DeclaredEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __add__(self, other: "DeclaredState") -> "DeclaredState":
        return DeclaredState(
            subsystems=[*self.subsystems, *other.subsystems],
            edges=[*self.edges, *other.edges],
            warnings=[*self.warnings, *other.warnings],
        )
