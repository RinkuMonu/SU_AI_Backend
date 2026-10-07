from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional
import re

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
    sub_category: str | None = None
    business_description: str | None = None
    tagline: str | None = None
    registration_number: str | None = None
    year_established: str | None = None
    number_of_employees: str | None = None

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
    name: str
    email: EmailStr
    role: str = "user"
    email_verified: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

class OTPResendRequest(BaseModel):
    email: EmailStr
