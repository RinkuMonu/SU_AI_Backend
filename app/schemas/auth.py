from pydantic import BaseModel, EmailStr, Field, model_validator, ConfigDict
from typing import Optional, Any

class SignupRequest(BaseModel):
    firstName: Optional[str] = Field(
        default=None, 
        description="First name (e.g. Sejal)", 
        json_schema_extra={"example": "Sejal"}
    )
    lastName: Optional[str] = Field(
        default=None, 
        description="Last name (e.g. Gupta)", 
        json_schema_extra={"example": "Gupta"}
    )
    contactNumber: Optional[str] = Field(
        default=None, 
        description="Contact / Phone number (e.g. +91 98765 43210)", 
        json_schema_extra={"example": "+91 98765 43210"}
    )
    email: EmailStr = Field(
        description="Email address", 
        json_schema_extra={"example": "sejalgupta1838@gmail.com"}
    )
    otp: Optional[str] = Field(
        default=None, 
        description="6-digit email verification OTP (from Verify Email OTP field)", 
        json_schema_extra={"example": "123456"}
    )
    password: str = Field(
        description="Account password", 
        json_schema_extra={"example": "SecurePassword@123"}
    )
    fullName: Optional[str] = Field(
        default=None, 
        description="Full name (optional, auto-derived from firstName + lastName if omitted)", 
        json_schema_extra={"example": "Sejal Gupta"}
    )
    name: Optional[str] = Field(default=None, description="Alternative alias for fullName")
    phone: Optional[str] = Field(default=None, description="Alternative alias for contactNumber")
    accountType: Optional[str] = Field(
        default="business", 
        description="Account type (default: business)", 
        json_schema_extra={"example": "business"}
    )
    termsAccepted: Optional[bool] = Field(
        default=True, 
        description="Accept terms and conditions", 
        json_schema_extra={"example": True}
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "firstName": "Sejal",
                "lastName": "Gupta",
                "contactNumber": "+91 98765 43210",
                "email": "sejalgupta1838@gmail.com",
                "otp": "123456",
                "password": "SecurePassword@123",
                "accountType": "business",
                "termsAccepted": True
            }
        }
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Map snake_case / alternative aliases to canonical fields
            if "first_name" in data and not data.get("firstName"):
                data["firstName"] = data["first_name"]
            if "last_name" in data and not data.get("lastName"):
                data["lastName"] = data["last_name"]
            if "full_name" in data and not data.get("fullName"):
                data["fullName"] = data["full_name"]
            if "contact_number" in data and not data.get("contactNumber"):
                data["contactNumber"] = data["contact_number"]
            if "phone_number" in data and not data.get("contactNumber"):
                data["contactNumber"] = data["phone_number"]
            if "phoneNumber" in data and not data.get("contactNumber"):
                data["contactNumber"] = data["phoneNumber"]
            if "email_otp" in data and not data.get("otp"):
                data["otp"] = data["email_otp"]
            if "emailOtp" in data and not data.get("otp"):
                data["otp"] = data["emailOtp"]
            if "account_type" in data and not data.get("accountType"):
                data["accountType"] = data["account_type"]
            if "terms_accepted" in data and not data.get("termsAccepted"):
                data["termsAccepted"] = data["terms_accepted"]
        return data

    @model_validator(mode="after")
    def resolve_fields(self):
        # Resolve full name
        if not self.fullName:
            if self.firstName or self.lastName:
                self.fullName = f"{self.firstName or ''} {self.lastName or ''}".strip()
            elif self.name:
                self.fullName = self.name
            else:
                self.fullName = self.email.split('@')[0]
        
        # Resolve first & last name if fullName was passed
        if self.fullName and not self.firstName:
            parts = self.fullName.split(" ", 1)
            self.firstName = parts[0]
            if len(parts) > 1 and not self.lastName:
                self.lastName = parts[1]

        # Resolve phone / contactNumber
        if not self.phone and self.contactNumber:
            self.phone = self.contactNumber
        elif not self.contactNumber and self.phone:
            self.contactNumber = self.phone

        if not self.accountType:
            self.accountType = "business"
            
        if self.termsAccepted is None:
            self.termsAccepted = True

        return self

class SendOTPRequest(BaseModel):
    email: EmailStr = Field(description="Email address to receive 6-digit OTP", json_schema_extra={"example": "sejalgupta1838@gmail.com"})
    name: Optional[str] = Field(default=None, description="Recipient name", json_schema_extra={"example": "Sejal Gupta"})

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "sejalgupta1838@gmail.com",
                "name": "Sejal Gupta"
            }
        }
    )

class VerifyOTPRequest(BaseModel):
    email: EmailStr = Field(description="Email address", json_schema_extra={"example": "sejalgupta1838@gmail.com"})
    otp: str = Field(description="6-digit verification code", json_schema_extra={"example": "123456"})

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "sejalgupta1838@gmail.com",
                "otp": "123456"
            }
        }
    )

class LoginRequest(BaseModel):
    email: EmailStr = Field(description="Account email address", json_schema_extra={"example": "sejalgupta1838@gmail.com"})
    password: str = Field(description="Account password", json_schema_extra={"example": "SecurePassword@123"})

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "sejalgupta1838@gmail.com",
                "password": "SecurePassword@123"
            }
        }
    )

class VerifyEmailRequest(BaseModel):
    token: Optional[str] = Field(default=None, description="Email verification token", json_schema_extra={"example": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."})
    link: Optional[str] = Field(default=None, description="Full verification link")

class ResendVerificationRequest(BaseModel):
    email: EmailStr = Field(description="Email address", json_schema_extra={"example": "sejalgupta1838@gmail.com"})
    force: Optional[bool] = False

class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(description="Registered email address", json_schema_extra={"example": "sejalgupta1838@gmail.com"})

class ResetPasswordRequest(BaseModel):
    token: Optional[str] = None
    link: Optional[str] = None
    newPassword: str = Field(description="New password", json_schema_extra={"example": "NewSecurePassword@123"})
    confirmPassword: Optional[str] = None



