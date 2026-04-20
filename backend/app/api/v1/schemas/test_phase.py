# backend/app/api/v1/schemas/test_phase.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TestPhaseCreate(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: str = "pending"


class TestPhaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    order: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


class TestPhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    order: int
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    status: str
