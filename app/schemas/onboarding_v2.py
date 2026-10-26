from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator


# ── Role Selection ──
class RoleSelectRequest(BaseModel):
    role: str = Field(..., description="Allowed roles are 'business' and 'influencer'")


class RoleSelectResponse(BaseModel):
    success: bool = True
    message: str
    role: str
    next_step: str


# ── Step 1: Online Presence ──
ALLOWED_PRESENCE_TYPES = {
    "website",
    "google_maps",
    "marketplace",
    "marketplaces",
    "wholesale_b2b",
    "b2c_online",
    "social_only",
    "none",
}

class OnlinePresenceRequest(BaseModel):
    presence_types: List[str] = Field(..., description="List of presence types")

    @field_validator("presence_types")
    @classmethod
    def validate_presence(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one presence type must be selected.")
        cleaned = [p.strip().lower() for p in v]
        for p in cleaned:
            if p not in ALLOWED_PRESENCE_TYPES:
                raise ValueError(f"Invalid presence type: '{p}'. Allowed values: {sorted(list(ALLOWED_PRESENCE_TYPES))}")
        
        # 'none' must be mutually exclusive
        if "none" in cleaned and len(cleaned) > 1:
            raise ValueError("'none' (No Online Presence) cannot be combined with other presence types.")
        
        return list(dict.fromkeys(cleaned))  # deduplicate


class OnlinePresenceResponse(BaseModel):
    success: bool = True
    message: str
    presence_types: List[str]
    next_step: str


# ── Step 2: Business Links ──
class BusinessLinkCreate(BaseModel):
    type: str = Field(..., description="website, google_maps, marketplace, wholesale_b2b, b2c_online, social_media")
    url: str = Field(..., description="Full URL")
    platform: Optional[str] = Field(None, description="Platform identifier (e.g., amazon, flipkart, instagram)")


class BusinessLinkUpdate(BaseModel):
    type: Optional[str] = None
    url: Optional[str] = None
    platform: Optional[str] = None


class BusinessLinkResponse(BaseModel):
    link_id: str
    type: str
    url: str
    platform: Optional[str] = None
    fetch_status: str = "pending"  # pending, completed, failed
    created_at: Optional[datetime] = None


# ── Step 3: Extracted Details ──
class ExtractedDetailsDraft(BaseModel):
    link_id: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    location: Optional[str] = None
    products: List[str] = []
    social_links: Dict[str, str] = {}
    is_confirmed: bool = False
    fetched_at: Optional[datetime] = None


# ── Step 4: Business Details ──
class BusinessDetailsUpdate(BaseModel):
    business_name: Optional[str] = None
    category: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    pincode: Optional[str] = None
    full_address: Optional[str] = None
    preferred_language: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    services: Optional[List[str]] = None


# ── Step 5: Business Photos ──
class BusinessPhotoItem(BaseModel):
    photo_id: str
    url: str
    caption: Optional[str] = None
    is_primary: bool = False
    uploaded_at: datetime


# ── Step 6: Social Accounts ──
class SocialConnectRequest(BaseModel):
    platform: str = Field(..., description="instagram, facebook, youtube, whatsapp_business, google_business")
    access_token: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None


class SocialAccountItem(BaseModel):
    platform: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    connected: bool = True
    connected_at: Optional[datetime] = None


# ── Step 7: AI Photos ──
class AiPhotoGenerateRequest(BaseModel):
    prompt: Optional[str] = None
    style: Optional[str] = "professional"
    aspect_ratio: Optional[str] = "1:1"


class AiPhotoConcept(BaseModel):
    concept_id: str
    title: str
    description: str
    preview_url: str


class AiPhotoVariation(BaseModel):
    variation_id: str
    title: str
    image_url: str


class AiPhotosResponse(BaseModel):
    success: bool = True
    status: str = "completed"
    concepts: List[AiPhotoConcept] = []
    variations: List[AiPhotoVariation] = []
    credits_used: int = 1
    credits_remaining: int = 100


# ── Step 8: Profile Comparison ──
class ProfileStrengthItem(BaseModel):
    title: str
    completed: bool
    weight: int
    recommendation: Optional[str] = None


class BusinessProfileComparisonResponse(BaseModel):
    overall_score: int  # 0 to 100
    grade: str  # Excellent, Good, Average, Incomplete
    checklist: List[ProfileStrengthItem]
    recommendations: List[str]


# ── Step 9: App Rating ──
class OnboardingRatingRequest(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None
    skipped: bool = False


# ── Step 10: Subscription ──
class SelectPlanRequest(BaseModel):
    plan_id: str
    billing_cycle: str = "monthly"


# ── Influencer Onboarding ──
class InfluencerDetailsUpdate(BaseModel):
    creator_name: Optional[str] = None
    display_name: Optional[str] = None
    profile_photo_url: Optional[str] = None
    bio: Optional[str] = None
    niche: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    preferred_language: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    location: Optional[str] = None
    collaboration_preferences: Optional[List[str]] = None
    content_types: Optional[List[str]] = None


class InfluencerMediaKitRequest(BaseModel):
    rates: Optional[Dict[str, float]] = None
    audience_demographics: Optional[Dict[str, Any]] = None
    top_content_links: Optional[List[str]] = None
    contact_email: Optional[str] = None
    bio_summary: Optional[str] = None


# ── Progress API ──
class OnboardingProgressResponse(BaseModel):
    role: Optional[str]
    current_step: str
    completed_steps: List[str]
    completion_percentage: int
    next_step: str
    is_completed: bool = False
