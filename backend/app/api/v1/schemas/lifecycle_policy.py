from pydantic import BaseModel, ConfigDict, Field


class EnvironmentLifecyclePolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idle_detection_enabled: bool
    idle_threshold_days: int
    decommission_notice_days: int


class EnvironmentLifecyclePolicyUpdate(BaseModel):
    """The WRITE model. extra='forbid' and no id/timestamps — the frontend must
    not echo the read model back. B2 shipped a 422 on every save for want of
    this distinction, and a mocked service cannot notice."""

    model_config = ConfigDict(extra="forbid")

    idle_detection_enabled: bool
    idle_threshold_days: int = Field(ge=1, le=3650)
    decommission_notice_days: int = Field(ge=1, le=365)


class DecommissionStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    description: str | None
    display_order: int
    is_required: bool
    is_active: bool


class DecommissionStepWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = None
    display_order: int = 0
    is_required: bool = True
    is_active: bool = True
