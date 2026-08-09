from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# The vocabulary `required_attributes` is drawn from. 'tier' is deliberately
# absent: environment.tier_id is already nullable=False, so requiring it would
# be a check that can never fail — a permanently-green row that reads as
# governance.
FIXED_ATTRIBUTES = {"owner", "expiry", "operations_group"}
CUSTOM_FIELD_PREFIX = "cf:"


class EnvironmentNamingPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    name_pattern: Optional[str] = None
    name_pattern_example: Optional[str] = None
    required_attributes: list[str] = []
    grace_days: int
    effective_from: datetime


class EnvironmentNamingPolicyUpdate(BaseModel):
    # forbid: POST /projects silently discarded priority_rank for the want of
    # exactly this, and POST /tenant/lifecycle-templates still drops
    # required_fields today. A dropped key here would leave an admin believing
    # a rule is in force that is not.
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    # The lengths mirror the columns (String(500)/String(200)) and
    # environment_compliance_service.MAX_PATTERN_LENGTH/MAX_NAME_LENGTH. The
    # service checks the pattern length again on its own account, because a
    # pattern can reach it straight from the database without passing here.
    name_pattern: Optional[str] = Field(default=None, max_length=500)
    name_pattern_example: Optional[str] = Field(default=None, max_length=200)
    required_attributes: list[str] = []
    grace_days: int = Field(default=14, ge=0, le=365)
