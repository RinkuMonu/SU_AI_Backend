from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional
from enum import Enum
import re

class UserRole(str, Enum):
    BUSINESSMAN = "businessman"
    INFLUENCER = "influencer"
    ADMIN = "admin"


class UserCreate(BaseModel):
    name: str | None = None
    fullName: str | None = None
    full_name: str | None = None
    phone_number: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: EmailStr | str
    password: str
    confirmPassword: str | None = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')
        return v

    @model_validator(mode='after')
    def validate_registration_fields(self) -> 'UserCreate':
        if self.confirmPassword is not None and self.password != self.confirmPassword:
            raise ValueError('Passwords do not match')
        if not (self.phone_number or self.phone or self.mobile):
            raise ValueError('Mobile phone number is required for registration')
        if not self.email or not str(self.email).strip():
            raise ValueError('Email address is required for registration')
        return self

class UserLogin(BaseModel):
    phone_number: str | None = None
    phone: str | None = None
    mobile: str | None = None
    username: str | None = None
    email: EmailStr | str | None = None
    Email: EmailStr | str | None = None
    password: str | None = None
    Password: str | None = None
    otp: str | None = None

class UserResponse(BaseModel):
    id: str
    name: str
    phone_number: Optional[str] = None
    phone_verified: bool = False
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    email_verified: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class OTPVerifyRequest(BaseModel):
    phone_number: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: EmailStr | str | None = None
    otp: str

class OTPResendRequest(BaseModel):
    phone_number: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: EmailStr | str | None = None

class RoleSelectRequest(BaseModel):
    role: str
    user_id: Optional[str] = None

class RoleSelectResponse(UserResponse):
    success: bool = True
    message: str = "Role selected successfully."
    user: Optional[UserResponse] = None

class DashboardRouteResponse(BaseModel):
    role: Optional[str] = None
    dashboard_route: str
    dashboard_name: str

