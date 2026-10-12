from pydantic import EmailStr, Field, model_validator
from app.models.base import MongoBaseModel
from typing import Optional, List, Any
from datetime import datetime

class User(MongoBaseModel):
    fullName: Optional[str] = None
    name: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: EmailStr
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    hashed_password: str
    accountType: str = "business"
    authProviders: List[str] = Field(default_factory=lambda: ["email"])
    emailVerified: bool = False
    email_verified: bool = False
    emailVerifiedAt: Optional[datetime] = None
    verificationToken: Optional[str] = None
    resetPasswordToken: Optional[str] = None
    resetPasswordExpiresAt: Optional[datetime] = None
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False
    role: str = "user"
    onboarding_step: Optional[int] = 1

    @model_validator(mode="before")
    @classmethod
    def populate_names_and_compatibility(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Resolve name and fullName
            full_name = data.get("fullName") or data.get("name") or data.get("full_name")
            if full_name:
                data["fullName"] = full_name
                if not data.get("name"):
                    data["name"] = full_name
            elif "email" in data:
                derived = str(data["email"]).split("@")[0]
                data["fullName"] = derived
                data["name"] = derived

            # Resolve email verification flags
            verified = data.get("emailVerified", data.get("email_verified", False))
            data["emailVerified"] = verified
            data["email_verified"] = verified

        return data


