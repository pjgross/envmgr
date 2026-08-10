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


class EnvironmentNamingPolicyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An omitted key (or null) means "keep what is saved", so `{}` previews the
    # policy currently in force. There is deliberately no way to preview
    # REMOVING a pattern: that would need a sentinel distinct from both, and the
    # honest answer to that question is the attributes-only policy an admin can
    # already save and preview directly.
    name_pattern: Optional[str] = Field(default=None, max_length=500)
    required_attributes: Optional[list[str]] = None


class EnvironmentNamingPolicyPreview(BaseModel):
    total_environments: int
    in_gap: int
    quarantined_now: int
    # Capped at the service's _PREVIEW_SAMPLE_LIMIT. The COUNTS above are exact
    # — a UI that renders the sample as if it were the whole set is lying, and
    # must say "showing the first N".
    sample_names: list[str]
