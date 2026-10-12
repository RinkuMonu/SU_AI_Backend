from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class SignupRequest(BaseModel):
    fullName: str
    email: EmailStr
    password: str
    accountType: str
    termsAccepted: bool

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class VerifyEmailRequest(BaseModel):
    token: Optional[str] = None
    link: Optional[str] = None

class ResendVerificationRequest(BaseModel):
    email: EmailStr
    force: Optional[bool] = False

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: Optional[str] = None
    link: Optional[str] = None
    newPassword: str
    confirmPassword: Optional[str] = None


