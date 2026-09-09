from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditNote(BaseModel):
    """Body of the four audit routes. `extra="forbid"`: the lifecycle-template
    endpoint's silent-drop history is why every new request schema forbids."""
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(None, max_length=2000)
