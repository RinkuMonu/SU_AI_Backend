from typing import Optional, List, Any
from datetime import datetime
from pydantic import EmailStr, Field, model_validator
from app.models.base import MongoBaseModel

class User(MongoBaseModel):
    name: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    phone_verified: bool = False
    hashed_password: str = ""
    accountType: str = "business"
    authProviders: List[str] = Field(default_factory=lambda: ["email"])
    googleId: Optional[str] = None
    email_verified: bool = False
    email_verified_at: Optional[datetime] = None
    verification_token: Optional[str] = None
    resetPasswordToken: Optional[str] = None
    resetPasswordExpiresAt: Optional[datetime] = None
    termsAcceptedAt: Optional[datetime] = None
    profileImageUrl: Optional[str] = None
    image: Optional[str] = None
    preferredLanguage: Optional[str] = None
    onboardingCompleted: bool = False
    onboarding_completed_at: Optional[datetime] = None
    onboarding_status: Optional[str] = None
    role: Optional[str] = None
    onboarding_step: Optional[int] = 1
    online_presence: Optional[str] = None

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

    # Compatibility properties (excluded from MongoDB serialization)
    @property
    def fullName(self) -> Optional[str]:
        return self.name

    @fullName.setter
    def fullName(self, value: Optional[str]) -> None:
        self.name = value

    @property
    def phone(self) -> Optional[str]:
        return self.phone_number

    @phone.setter
    def phone(self, value: Optional[str]) -> None:
        self.phone_number = value

    @property
    def contactNumber(self) -> Optional[str]:
        return self.phone_number

    @contactNumber.setter
    def contactNumber(self, value: Optional[str]) -> None:
        self.phone_number = value

    @property
    def google_id(self) -> Optional[str]:
        return self.googleId

    @google_id.setter
    def google_id(self, value: Optional[str]) -> None:
        self.googleId = value

    @property
    def emailVerified(self) -> bool:
        return self.email_verified

    @emailVerified.setter
    def emailVerified(self, value: bool) -> None:
        self.email_verified = value

    @property
    def emailVerifiedAt(self) -> Optional[datetime]:
        return self.email_verified_at

    @emailVerifiedAt.setter
    def emailVerifiedAt(self, value: Optional[datetime]) -> None:
        self.email_verified_at = value

    @property
    def verificationToken(self) -> Optional[str]:
        return self.verification_token

    @verificationToken.setter
    def verificationToken(self, value: Optional[str]) -> None:
        self.verification_token = value

    @model_validator(mode="before")
    @classmethod
    def resolve_user_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Resolve canonical 'name' and pop 'fullName' / 'full_name'
            full_name = data.get("name") or data.get("fullName") or data.get("full_name")
            if not full_name:
                first = data.get("firstName") or ""
                last = data.get("lastName") or ""
                full_name = f"{first} {last}".strip()
            if not full_name and data.get("email"):
                full_name = str(data["email"]).split("@")[0]
            if not full_name:
                full_name = "User"
            data["name"] = full_name
            data.pop("fullName", None)
            data.pop("full_name", None)

            # Resolve canonical 'phone_number' and pop 'phone', 'contactNumber'
            pn = data.get("phone_number") or data.get("phone") or data.get("contactNumber")
            if pn:
                data["phone_number"] = pn
            data.pop("phone", None)
            data.pop("contactNumber", None)

            # Compatibility for image / profileImageUrl
            img = data.get("profileImageUrl") or data.get("image")
            if img:
                data["profileImageUrl"] = img
                data["image"] = img

            # Resolve canonical 'googleId' and pop 'google_id'
            gid = data.get("googleId") or data.get("google_id")
            if gid:
                data["googleId"] = gid
            data.pop("google_id", None)

            # Resolve canonical 'email_verified' and pop 'emailVerified'
            verified = data.get("email_verified", data.get("emailVerified", False))
            data["email_verified"] = verified
            data.pop("emailVerified", None)

            # Resolve canonical 'email_verified_at' and pop 'emailVerifiedAt'
            verified_at = data.get("email_verified_at") or data.get("emailVerifiedAt")
            if verified_at:
                data["email_verified_at"] = verified_at
            data.pop("emailVerifiedAt", None)

            # Resolve canonical 'verification_token' and pop 'verificationToken'
            vtoken = data.get("verification_token") or data.get("verificationToken")
            if vtoken is not None:
                data["verification_token"] = vtoken
            data.pop("verificationToken", None)

        return data
