from datetime import datetime
from typing import Optional, List, Dict, Any
import re
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator, ConfigDict, AliasChoices
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
    brand_description: Optional[str] = None
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
    completion_percentage: Optional[int] = 0
    completed_sections: Optional[List[str]] = Field(default_factory=list)
    pending_sections: Optional[List[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_description_and_name(self):
        desc = self.business_description or self.brand_description
        if desc:
            self.business_description = desc
            self.brand_description = desc
        name = self.business_name or self.brand_name
        if name:
            self.business_name = name
            self.brand_name = name
        return self

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
    completion_percentage: int = 0
    completed_sections: List[str] = Field(default_factory=list)
    pending_sections: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BrandKitStatusResponse(BaseModel):
    role: Optional[str] = None
    should_show_modal: bool
    brand_kit_status: str  # "not_started", "in_progress", "completed", "not_applicable"
    brand_kit_completed: bool
    brand_kit_completed_at: Optional[datetime] = None
    business_id: Optional[str] = None
    completion_percentage: int = 0
    completed_sections: List[str] = Field(default_factory=list)
    pending_sections: List[str] = Field(default_factory=list)
    brand_kit: Optional[Dict[str, Any]] = None


class BrandKitActionResponse(BaseModel):
    success: bool = True
    message: str
    brand_kit_status: str
    brand_kit_completed: bool
    completion_percentage: int = 0
    completed_sections: List[str] = Field(default_factory=list)
    pending_sections: List[str] = Field(default_factory=list)
    data: Optional[Dict[str, Any]] = None


class AILogoVariationItem(BaseModel):
    logo_url: str
    seed: int
    style: str


class AILogoGenerateResponse(BaseModel):
    logo_url: str
    business_name: str
    style: str
    prompt: str
    seed: Optional[int] = None
    variations: Optional[List[AILogoVariationItem]] = []


class AILogoGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    business_name: Optional[str] = Field(None, validation_alias=AliasChoices("business_name", "brand_name", "name"))
    brand_name: Optional[str] = None
    business_category: Optional[str] = Field(None, validation_alias=AliasChoices("business_category", "category", "industry"))
    style: Optional[str] = "minimalist_modern"
    preferred_colors: Optional[List[str]] = Field(default=None, validation_alias=AliasChoices("preferred_colors", "colors", "brand_colors"))
    prompt: Optional[str] = Field(None, validation_alias=AliasChoices("prompt", "description", "visual_theme"))
    tagline: Optional[str] = None
    brand_voice: Optional[str] = Field(None, validation_alias=AliasChoices("brand_voice", "tone", "personality"))
    personality: Optional[str] = None
    font: Optional[str] = None
    transparent_background: Optional[bool] = False
    variation_seed: Optional[int] = Field(None, validation_alias=AliasChoices("variation_seed", "seed"))
    num_variations: Optional[int] = Field(default=1, ge=1, le=4)
    save_to_brand_kit: Optional[bool] = False

    @field_validator("preferred_colors", mode="before")
    @classmethod
    def clean_colors(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if "," in s:
                raw_list = [c.strip() for c in s.split(",") if c.strip()]
            else:
                raw_list = [s]
        elif isinstance(v, (list, tuple)):
            raw_list = list(v)
        else:
            return []

        cleaned = []
        for c in raw_list:
            if not isinstance(c, str):
                continue
            s = c.strip()
            if not s:
                continue
            try:
                norm = validate_and_normalize_hex(s)
                if norm:
                    cleaned.append(norm)
            except Exception:
                if HEX_COLOR_REGEX.match(s if s.startswith("#") else f"#{s}"):
                    cleaned.append(s.upper() if s.startswith("#") else f"#{s.upper()}")
                else:
                    cleaned.append(s)
        return cleaned

    @field_validator("num_variations", mode="before")
    @classmethod
    def clean_num_variations(cls, v: Any) -> int:
        if v is None or v == "":
            return 1
        try:
            return max(1, min(4, int(v)))
        except (ValueError, TypeError):
            return 1

    @model_validator(mode="after")
    def sync_names(self):
        name = self.business_name or self.brand_name
        if name:
            self.business_name = name
            self.brand_name = name
        return self

