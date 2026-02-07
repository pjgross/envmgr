from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class TenantBase(BaseModel):
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=50)
    settings: Optional[dict] = None


class TenantCreate(TenantBase):
    pass


class TenantResponse(TenantBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserBase(BaseModel):
    username: str = Field(..., max_length=50)
    email: EmailStr
    role: str = "Viewer"
    notification_preferences: Optional[dict] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    tenant_id: int


class UserLogin(BaseModel):
    username: str
    password: str
    tenant_slug: str


class UserResponse(UserBase):
    id: int
    tenant_id: int
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
