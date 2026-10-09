from pydantic import EmailStr
from app.models.base import MongoBaseModel


class User(MongoBaseModel):
    name: str
    email: EmailStr
    hashed_password: str
    role: str = "user"
    email_verified: bool = True
    
    # Business Registration Fields
    business_logo: str | None = None
    brand_color: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    business_category: str | None = None
    business_description: str | None = None
    registration_number: str | None = None
    year_established: str | None = None
    
    # Business Location
    country: str | None = None
    state: str | None = None
    city: str | None = None
    area: str | None = None
    pincode: str | None = None
    full_address: str | None = None
    google_maps_url: str | None = None

    # Business Type
    business_model: str | None = None
    selling_model: str | None = None

    # Target Audience
    target_age_group: list[str] | None = None
    target_gender: str | None = None
    target_location: str | None = None
    customer_type: str | None = None
