from pydantic import EmailStr, Field
from app.models.base import MongoBaseModel
from typing import Optional, List
from datetime import datetime

class User(MongoBaseModel):
    fullName: str
    email: EmailStr
    phone: Optional[str] = None
    hashed_password: str
    accountType: str = "personal"
    authProviders: List[str] = Field(default_factory=lambda: ["email"])
    emailVerified: bool = False
    emailVerifiedAt: Optional[datetime] = None
    verificationToken: Optional[str] = None
    resetPasswordToken: Optional[str] = None
    resetPasswordExpiresAt: Optional[datetime] = None
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False
    role: str = "user"

