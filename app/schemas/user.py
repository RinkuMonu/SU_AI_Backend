from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
import re
from app.models.base import PyObjectId

class UserCreate(BaseModel):
    name: str | None = None
    fullName: str | None = None
    full_name: str | None = None
    email: EmailStr
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
    def check_passwords_match(self) -> 'UserCreate':
        if self.confirmPassword is not None and self.password != self.confirmPassword:
            raise ValueError('Passwords do not match')
        return self

class UserLogin(BaseModel):
    email: EmailStr | None = None
    Email: EmailStr | None = None
    password: str | None = None
    Password: str | None = None


class UserResponse(BaseModel):
    id: str
    fullName: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    accountType: str = "business"
    authProviders: List[str] = Field(default_factory=lambda: ["email"])
    emailVerified: bool = False
    email_verified: bool = False
    isVerified: bool = False
    name: Optional[str] = None
    role: Optional[str] = "user"
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    image: Optional[str] = None
    avatar: Optional[str] = None
    businessName: Optional[str] = None
    businessCategory: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False

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

class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str
    confirmPassword: Optional[str] = None
