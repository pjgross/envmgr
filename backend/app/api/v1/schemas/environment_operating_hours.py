from typing import Optional, List
from pydantic import BaseModel


class OperatingHoursDay(BaseModel):
    closed: bool = False
    open: Optional[str] = None
    close: Optional[str] = None


class OperatingHoursConfigIn(BaseModel):
    timezone: str
    week: List[OperatingHoursDay]


class OperatingHoursConfigResponse(BaseModel):
    configured: bool
    timezone: Optional[str] = None
    week: Optional[List[OperatingHoursDay]] = None


class EnvironmentUtilization(BaseModel):
    environment_id: int
    environment_name: str
    configured: bool
    timezone: Optional[str] = None
    total_operating_seconds: float
    booked_operating_seconds: float
    utilization_pct: float


class UtilizationOverview(BaseModel):
    rows: List[EnvironmentUtilization]
    unconfigured_count: int
