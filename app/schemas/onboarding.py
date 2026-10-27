from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

class BusinessOnlinePresenceType(str, Enum):
    WEBSITE = "website"
    GOOGLE_MAPS = "google_maps"
    MARKETPLACE_SELLER = "marketplace_seller"
    NO_ONLINE_PRESENCE = "no_online_presence"
    WHOLESALE_B2B = "wholesale_b2b"
    OTHER = "other"
    SOMETHING_ELSE = "something_else"

VALID_ONLINE_PRESENCE_OPTIONS = {
    "website",
    "google_maps",
    "marketplace_seller",
    "no_online_presence",
    "wholesale_b2b",
    "other",
    "something_else"
}

class OnlinePresenceRequest(BaseModel):
    online_presence: str = Field(..., description="Selected business online presence option")
    google_maps_url: Optional[str] = None
    website_url: Optional[str] = None
    website: Optional[str] = None
    marketplace_name: Optional[str] = None
    marketplace_url: Optional[str] = None
    selected_platforms: Optional[List[str]] = Field(default=None, description="Array of selected marketplace or B2B platforms")
    platform_urls: Optional[Dict[str, str]] = Field(default=None, description="Map of platform IDs to URLs")
    urls: Optional[List[Dict[str, str]]] = Field(default=None, description="Optional array of platform URL mappings")
    custom_platform_name: Optional[str] = Field(default=None, description="Custom platform name if 'other' is selected")
    other_platform_name: Optional[str] = Field(default=None, description="Alias for custom_platform_name")
    has_storefront: Optional[bool] = None
    website_skipped: Optional[bool] = None
    business_type: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class OnlinePresenceResponse(BaseModel):
    success: bool = True
    message: str = "Business online presence saved successfully."
    online_presence: str
    business_type: Optional[str] = None
    onboarding_step: int = 2
    onboarding_status: str = "in_progress"
    next_step: str = "brand_kit"
    can_access_dashboard: bool = False
    data: Optional[Dict[str, Any]] = None
