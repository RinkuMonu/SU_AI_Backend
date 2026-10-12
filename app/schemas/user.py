from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from app.models.base import PyObjectId

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
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False

class UserPreferencesUpdate(BaseModel):
    preferredLanguage: Optional[str] = None
    primaryGoal: Optional[str] = None
    targetPlatforms: Optional[List[str]] = None
    onboardingCompleted: Optional[bool] = None

class UserUpdate(BaseModel):
    fullName: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    profileImageUrl: Optional[str] = None
