from pydantic import BaseModel, EmailStr, Field, field_validator
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
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    slug: Optional[str] = Field(None, max_length=50)
    settings: Optional[dict] = None


class TenantAdminSettings(BaseModel):
    settings: dict


class UserBase(BaseModel):
    username: str = Field(..., max_length=50)
    email: EmailStr
    role: str = "Viewer"
    notification_preferences: Optional[dict] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid_roles = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}
        if v not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}")
        return v


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
    is_master_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserAdminCreate(BaseModel):
    username: str = Field(..., max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: str = "Viewer"
    is_master_admin: bool = False

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid_roles = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}
        if v not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}")
        return v


class UserAdminUpdate(BaseModel):
    username: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    is_master_admin: Optional[bool] = None


class UserRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid_roles = {"Admin", "Release Manager", "Test Manager", "Developer", "Viewer"}
        if v not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}")
        return v


class ImpersonationToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    target_tenant: TenantResponse


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
