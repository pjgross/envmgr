from pydantic import BaseModel


class CoverageSystem(BaseModel):
    system_id: int
    system_name: str
    role: str  # 'changing' | 'regression'


class CoverageEnvironment(BaseModel):
    environment_id: int
    name: str
    tier_name: str
    status: str
    covered_system_ids: list[int]


class ReleaseEnvironmentCoverageRead(BaseModel):
    needed_systems: list[CoverageSystem]
    environments: list[CoverageEnvironment]
    uncovered_system_ids: list[int]
