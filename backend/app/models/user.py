"""
Pydantic models for User/Auth.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    token: str = Field(..., min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None
    is_superadmin: bool = False
    organization_id: Optional[str] = None
    is_read_only: bool = False
    assigned_funnel_id: Optional[str] = None
    is_org_admin: bool = True
    # Menu lateral resolvido (defaults mergeados) da organização efetiva.
    menu_config: dict[str, bool] = Field(default_factory=dict)
