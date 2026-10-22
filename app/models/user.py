from typing import Optional, List, Any
from datetime import datetime
from pydantic import EmailStr, Field, model_validator
from app.models.base import MongoBaseModel

class User(MongoBaseModel):
    fullName: Optional[str] = None
    name: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    phone: Optional[str] = None
    contactNumber: Optional[str] = None
    phone_verified: bool = False
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
    image: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False
    role: Optional[str] = None
    onboarding_step: Optional[int] = 1

    # Business Registration Fields
    business_logo: Optional[str] = None
    brand_color: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    registration_number: Optional[str] = None
    year_established: Optional[str] = None
    
    # Business Location
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    pincode: Optional[str] = None
    full_address: Optional[str] = None
    google_maps_url: Optional[str] = None

    # Business Type & Audience
    business_model: Optional[str] = None
    selling_model: Optional[str] = None
    target_age_group: Optional[List[str]] = None
    target_gender: Optional[str] = None
    target_location: Optional[str] = None
    customer_type: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def resolve_user_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Resolve name and fullName
            full_name = data.get("fullName") or data.get("name") or data.get("full_name")
            if not full_name:
                first = data.get("firstName") or ""
                last = data.get("lastName") or ""
                full_name = f"{first} {last}".strip()
            if not full_name and data.get("email"):
                full_name = str(data["email"]).split("@")[0]
            if not full_name:
                full_name = "User"

            data["fullName"] = full_name
            data["name"] = full_name

            # Compatibility for phone_number / phone / contactNumber
            pn = data.get("phone_number") or data.get("phone") or data.get("contactNumber")
            if pn:
                data["phone_number"] = pn
                data["phone"] = pn
                data["contactNumber"] = pn

            # Compatibility for image / profileImageUrl
            img = data.get("profileImageUrl") or data.get("image")
            if img:
                data["profileImageUrl"] = img
                data["image"] = img

            # Resolve email verification flags
            verified = data.get("emailVerified", data.get("email_verified", False))
            data["emailVerified"] = verified
            data["email_verified"] = verified

        return data
