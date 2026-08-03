from typing import Literal, Optional

from pydantic import BaseModel

Presence = Literal["both", "left_only", "right_only"]
DifferenceKind = Literal["presence", "mocked", "version", "host_shape"]


class ComparedEnvironment(BaseModel):
    id: int
    name: str
    status: str


class HostShapeEntry(BaseModel):
    """How many hosts of a given type and role, never which hosts.

    Host names differ between environments by design, so identity is not
    compared — see docs/superpowers/specs/2026-08-03-environment-comparison-design.md.
    """
    component_type: str
    role: Optional[str] = None
    count: int


class SystemPresence(BaseModel):
    system_id: int
    name: str
    presence: Presence


class SubsystemSide(BaseModel):
    is_mocked: bool
    # Displayed, never compared: free text would make every mocked subsystem differ.
    mock_notes: Optional[str] = None
    version: Optional[str] = None
    host_shape: list[HostShapeEntry]


class SubsystemComparison(BaseModel):
    subsystem_id: int
    name: str
    system_id: int
    system_name: str
    presence: Presence
    left: Optional[SubsystemSide] = None
    right: Optional[SubsystemSide] = None
    differences: list[DifferenceKind]


class ComparisonSummary(BaseModel):
    compared: int
    differing: int
    by_kind: dict[str, int]


class EnvironmentComparisonResponse(BaseModel):
    left: ComparedEnvironment
    right: ComparedEnvironment
    systems: list[SystemPresence]
    subsystems: list[SubsystemComparison]
    summary: ComparisonSummary
