from datetime import datetime
from typing import Optional, List, Dict, Any
import re
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.models.base import PyObjectId

HEX_COLOR_REGEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

def validate_and_normalize_hex(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if not s.startswith("#"):
        s = f"#{s}"
    if not HEX_COLOR_REGEX.match(s):
        raise ValueError(f"Invalid hexadecimal color: '{v}'. Must be valid #RGB or #RRGGBB format.")
    if len(s) == 4:
        s = f"#{s[1]*2}{s[2]*2}{s[3]*2}"
    return s.upper()


class GradientStop(BaseModel):
    color: str
    position: Optional[float] = Field(None, ge=0.0, le=100.0)

    @field_validator("color")
    @classmethod
    def validate_stop_color(cls, v: str) -> str:
        validated = validate_and_normalize_hex(v)
        if not validated:
            raise ValueError("Gradient stop color is required and must be a valid hex code.")
        return validated


class GradientConfig(BaseModel):
    gradient_type: str = "linear"  # "linear" or "radial"
    angle: Optional[float] = Field(90.0, ge=0.0, le=360.0)
    stops: List[GradientStop] = []

    @field_validator("gradient_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        val = str(v).lower().strip()
        if val not in ["linear", "radial"]:
            raise ValueError("Gradient type must be 'linear' or 'radial'.")
        return val


class ContactInfo(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None


class LocationInfo(BaseModel):
    city: Optional[str] = None
    state: Optional[str] = None


class BrandBase(BaseModel):
    business_name: Optional[str] = None
    brand_name: Optional[str] = None
    business_type: Optional[str] = None
    registration_number: Optional[str] = None
    business_model: Optional[str] = None
    selling_model: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    logo_url: Optional[str] = None
    logo_metadata: Optional[Dict[str, Any]] = None
    tagline: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    gradient: Optional[GradientConfig] = None
    font: Optional[str] = None
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    brand_voice: Optional[str] = None
    target_audience: Optional[str] = None
    age_group: Optional[str] = None
    age_groups: Optional[List[str]] = None
    gender: Optional[str] = None
    customer_type: Optional[str] = None
    location_focus: Optional[str] = None
    language: Optional[str] = None
    generating_for: Optional[List[str]] = None
    tone: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    contact: Optional[ContactInfo] = None
    location: Optional[LocationInfo] = None
    social_style: Optional[str] = None

    @field_validator("primary_color", "secondary_color", "accent_color")
    @classmethod
    def validate_colors(cls, v: Optional[str]) -> Optional[str]:
        return validate_and_normalize_hex(v)


class BrandCreate(BrandBase):
    pass


class BrandUpdate(BrandBase):
    pass


class BrandKitSubmission(BrandBase):
    is_draft: bool = False


class BrandResponse(BrandBase):
    id: Optional[PyObjectId] = None
    business_id: Optional[str] = None
    owner_id: Optional[str] = None
    brand_kit_status: str = "not_started"
    brand_kit_completed: bool = False
    brand_kit_completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BrandKitStatusResponse(BaseModel):
    role: Optional[str] = None
    should_show_modal: bool
    brand_kit_status: str  # "not_started", "in_progress", "completed", "not_applicable"
    brand_kit_completed: bool
    brand_kit_completed_at: Optional[datetime] = None
    business_id: Optional[str] = None
    brand_kit: Optional[Dict[str, Any]] = None


class BrandKitActionResponse(BaseModel):
    success: bool = True
    message: str
    brand_kit_status: str
    brand_kit_completed: bool
    data: Optional[Dict[str, Any]] = None


class AILogoGenerateRequest(BaseModel):
    business_name: str
    business_category: Optional[str] = None
    style: Optional[str] = "modern luxury minimalist vector emblem"
    preferred_colors: Optional[List[str]] = None

