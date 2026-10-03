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
