from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from app.models.base import PyObjectId

class UserResponse(BaseModel):
    id: str
    fullName: str
    email: EmailStr
    phone: Optional[str] = None
    accountType: str
    authProviders: List[str]
    emailVerified: bool
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool

class UserPreferencesUpdate(BaseModel):
    preferredLanguage: Optional[str] = None
    primaryGoal: Optional[str] = None
    targetPlatforms: Optional[List[str]] = None
    onboardingCompleted: Optional[bool] = None

class UserUpdate(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    profileImageUrl: Optional[str] = None
