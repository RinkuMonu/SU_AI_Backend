from pydantic import EmailStr, Field
from app.models.base import MongoBaseModel
from typing import Optional, List
from datetime import datetime

class User(MongoBaseModel):
    fullName: str
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
    name: Optional[str] = None

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

