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

    @model_validator(mode="before")
    @classmethod
    def resolve_compatibility(cls, data: Any):
        if isinstance(data, dict):
            # Resolve fullName & name
            full_name = data.get("fullName") or data.get("name")
            if not full_name:
                first = data.get("firstName") or ""
                last = data.get("lastName") or ""
                full_name = f"{first} {last}".strip()
            if not full_name and data.get("email"):
                full_name = str(data["email"]).split("@")[0]
            if not full_name:
                full_name = "User"

            data["fullName"] = full_name
            if not data.get("name"):
                data["name"] = full_name

            # Compatibility for phone / contactNumber
            if "phone" in data and not data.get("contactNumber"):
                data["contactNumber"] = data["phone"]
            if "contactNumber" in data and not data.get("phone"):
                data["phone"] = data["contactNumber"]

            # Compatibility for email_verified / emailVerified
            if "email_verified" in data and not data.get("emailVerified"):
                data["emailVerified"] = data["email_verified"]
            if "emailVerified" in data and not data.get("email_verified"):
                data["email_verified"] = data["emailVerified"]

            # Compatibility for role
            if not data.get("role"):
                data["role"] = "user"

        return data


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

