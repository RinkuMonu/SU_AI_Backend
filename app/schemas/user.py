from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum
import re
from app.models.base import PyObjectId

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
    role: str | None = "business"
    
    # Business Registration Fields
    business_logo: str | None = None
    brand_color: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    business_category: str | None = None
    business_description: str | None = None
    registration_number: str | None = None
    year_established: str | None = None

    # Business Location
    country: str | None = None
    state: str | None = None
    city: str | None = None
    area: str | None = None
    pincode: str | None = None
    full_address: str | None = None
    google_maps_url: str | None = None

    # Business Type
    business_model: str | None = None
    selling_model: str | None = None

    # Target Audience
    target_age_group: list[str] | None = None
    target_gender: str | None = None
    target_location: str | None = None
    customer_type: str | None = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 1:
            raise ValueError('Password must be at least 1 characters long')
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
    name: Optional[str] = None
    fullName: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    phone_verified: bool = False
    role: Optional[str] = None
    accountType: str = "business"
    authProviders: List[str] = Field(default_factory=lambda: ["email"])
    emailVerified: bool = False
    email_verified: bool = True
    isVerified: bool = False
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    image: Optional[str] = None
    avatar: Optional[str] = None
    businessName: Optional[str] = None
    businessCategory: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False

    @model_validator(mode="before")
    @classmethod
    def populate_response_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            fn = data.get("fullName") or data.get("name")
            data["fullName"] = fn
            data["name"] = fn
            pn = data.get("phone_number") or data.get("phone") or data.get("contactNumber")
            data["phone_number"] = pn
            data["phone"] = pn
            data["contactNumber"] = pn
        return data


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[UserResponse] = None
    role: Optional[str] = None
    requires_role_selection: bool = False
    dashboard_route: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    preferredLanguage: Optional[str] = None
    primaryGoal: Optional[str] = None
    targetPlatforms: Optional[List[str]] = None
    onboardingCompleted: Optional[bool] = None


class UserUpdate(BaseModel):
    fullName: Optional[str] = None
    name: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    profileImageUrl: Optional[str] = None
    image: Optional[str] = None
    avatar: Optional[str] = None
    businessName: Optional[str] = None
    businessCategory: Optional[str] = None
    accountType: Optional[str] = None
    role: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: Optional[bool] = None
    onboardingData: Optional[dict] = None
    onboarding_step: Optional[int] = None

    model_config = {
        "extra": "allow"
    }


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str
    confirmPassword: Optional[str] = None


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
