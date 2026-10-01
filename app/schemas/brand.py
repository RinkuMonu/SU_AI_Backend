from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class ContactInfo(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None


class LocationInfo(BaseModel):
    city: Optional[str] = None
    state: Optional[str] = None


class BrandCreate(BaseModel):
    logo_url: Optional[str] = None

    primary_color: Optional[str] = None

    secondary_color: Optional[str] = None

    font: Optional[str] = None

    tone: Optional[str] = None

    brand_description: Optional[str] = None

    target_audience: Optional[str] = None

    website: Optional[str] = None

    instagram: Optional[str] = None

    contact: Optional[ContactInfo] = None

    location: Optional[LocationInfo] = None

    social_style: Optional[str] = None


class BrandUpdate(BaseModel):
    logo_url: Optional[str] = None

    primary_color: Optional[str] = None

    secondary_color: Optional[str] = None

    font: Optional[str] = None

    tone: Optional[str] = None

    brand_description: Optional[str] = None

    target_audience: Optional[str] = None

    website: Optional[str] = None

    instagram: Optional[str] = None

    contact: Optional[ContactInfo] = None

    location: Optional[LocationInfo] = None

    social_style: Optional[str] = None


from app.models.base import PyObjectId

class BrandResponse(BaseModel):
    id: PyObjectId
    business_id: str

    logo_url: Optional[str] = None

    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None

    font: Optional[str] = None
    tone: Optional[str] = None

    brand_description: Optional[str] = None
    target_audience: Optional[str] = None

    website: Optional[str] = None
    instagram: Optional[str] = None

    contact: Optional[ContactInfo] = None
    location: Optional[LocationInfo] = None

    social_style: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
