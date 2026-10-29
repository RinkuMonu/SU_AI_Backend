from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, AliasChoices

class BusinessOnlinePresenceType(str, Enum):
    WEBSITE = "website"
    GOOGLE_MAPS = "google_maps"
    MARKETPLACE = "marketplace"
    MARKETPLACE_SELLER = "marketplace_seller"
    B2B = "b2b"
    WHOLESALE = "wholesale"
    WHOLESALE_B2B = "wholesale_b2b"
    DIRECTORIES = "directories"
    NONE = "none"
    NO_ONLINE_PRESENCE = "no_online_presence"
    SOCIAL_MEDIA = "social_media"
    OTHER = "other"
    SOMETHING_ELSE = "something_else"

PRESENCE_CANONICAL_MAP: Dict[str, str] = {
    "website": "website",
    "google_maps": "google_maps",
    "marketplace": "marketplace_seller",
    "marketplace_seller": "marketplace_seller",
    "b2b": "wholesale_b2b",
    "wholesale": "wholesale_b2b",
    "wholesale_b2b": "wholesale_b2b",
    "directories": "wholesale_b2b",
    "none": "no_online_presence",
    "no_online_presence": "no_online_presence",
    "social_media": "social_media",
    "other": "other",
    "something_else": "something_else",
}

CANONICAL_TO_FRONTEND_MAP: Dict[str, str] = {
    "marketplace_seller": "marketplace",
    "wholesale_b2b": "b2b",
    "no_online_presence": "none",
    "social_media": "social_media",
    "website": "website",
    "google_maps": "google_maps",
    "other": "other",
    "something_else": "something_else",
}

VALID_ONLINE_PRESENCE_OPTIONS = set(PRESENCE_CANONICAL_MAP.keys())

class OnlinePresenceRequest(BaseModel):
    online_presence: str = Field(
        ...,
        validation_alias=AliasChoices("online_presence", "presence", "source", "business_source", "onlinePresence"),
        description="Selected business online presence option"
    )
    google_maps_url: Optional[str] = None
    website_url: Optional[str] = None
    website: Optional[str] = None
    marketplace_name: Optional[str] = None
    marketplace_url: Optional[str] = None
    selected_platforms: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("selected_platforms", "platforms", "selectedPlatforms"),
        description="Array of selected marketplace or B2B platforms"
    )
    directory_listings: Optional[List[str]] = Field(default=None, description="Optional directory listings for marketplace flow")
    additional_listings: Optional[List[str]] = Field(default=None, description="Optional additional listings for wholesale/B2B flow")
    custom_listing_name: Optional[str] = Field(default=None, description="Custom directory listing name if 'other' selected")
    platform_urls: Optional[Dict[str, str]] = Field(default=None, description="Map of platform IDs to URLs")
    urls: Optional[List[Dict[str, str]]] = Field(default=None, description="Optional array of platform URL mappings")
    custom_platform_name: Optional[str] = Field(default=None, description="Custom platform name if 'other' is selected")
    other_platform_name: Optional[str] = Field(default=None, description="Alias for custom_platform_name")
    selected_services: Optional[List[str]] = Field(default=None, description="Optional array of selected business services")
    selectedServices: Optional[List[str]] = Field(default=None, description="CamelCase alias for selected_services")
    has_storefront: Optional[bool] = None
    website_skipped: Optional[bool] = None
    skip_website: Optional[bool] = None
    business_type: Optional[str] = None
    selling_model: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class OnlinePresenceResponse(BaseModel):
    success: bool = True
    message: str = "Business online presence saved successfully."
    online_presence: str
    canonical_presence: Optional[str] = None
    business_source: Optional[str] = None
    presence: Optional[str] = None
    business_type: Optional[str] = None
    selling_model: Optional[str] = None
    selected_platforms: Optional[List[str]] = None
    directory_listings: Optional[List[str]] = None
    additional_listings: Optional[List[str]] = None
    onboarding_step: int = 2
    onboarding_status: str = "in_progress"
    next_step: str = "brand_kit"
    can_access_dashboard: bool = False
    data: Optional[Dict[str, Any]] = None


# ============================================================================
# Choose Your Business Services Onboarding Catalog & Schemas
# ============================================================================

class BusinessServiceType(str, Enum):
    AUTOMATE_SOCIAL_MEDIA = "automate_social_media"
    MARKETING_VIDEO = "marketing_video"
    FASHION_PHOTOSHOOT = "fashion_photoshoot"
    PRODUCT_PHOTOSHOOT = "product_photoshoot"
    AI_WEBSITE_BUILDER = "ai_website_builder"
    LEADS_CRM = "leads_crm"
    AI_MARKETING_AGENT = "ai_marketing_agent"


SUPPORTED_BUSINESS_SERVICES: List[Dict[str, Any]] = [
    {
        "id": "automate_social_media",
        "name": "Automate Social Media",
        "description": "Auto-generate, design, and schedule posts across Instagram, Facebook, and LinkedIn",
        "icon": "share-2",
        "category": "marketing",
    },
    {
        "id": "marketing_video",
        "name": "Marketing Video",
        "description": "Create high-converting vertical 9:16 promotional reels and video ads with AI",
        "icon": "video",
        "category": "content",
    },
    {
        "id": "fashion_photoshoot",
        "name": "Fashion AI Photoshoot",
        "description": "Virtual studio model photoshoots preserving garment style, color, and fabric",
        "icon": "camera",
        "category": "creative",
    },
    {
        "id": "product_photoshoot",
        "name": "Product AI Photoshoot",
        "description": "Commercial-grade studio product photography with realistic lighting and backgrounds",
        "icon": "package",
        "category": "creative",
    },
    {
        "id": "ai_website_builder",
        "name": "AI Website Builder",
        "description": "Generate dynamic, conversion-ready business websites with modern design in seconds",
        "icon": "globe",
        "category": "presence",
    },
    {
        "id": "leads_crm",
        "name": "Leads & CRM",
        "description": "Capture, organize, and track customer inquiries, leads, and conversion pipelines",
        "icon": "users",
        "category": "growth",
    },
    {
        "id": "ai_marketing_agent",
        "name": "AI Marketing Agent",
        "description": "Autonomous AI assistant that plans, executes, and optimizes marketing campaigns",
        "icon": "bot",
        "category": "agent",
    },
]

VALID_BUSINESS_SERVICE_IDS = {s["id"] for s in SUPPORTED_BUSINESS_SERVICES}
BUSINESS_SERVICE_MAP = {s["id"]: s for s in SUPPORTED_BUSINESS_SERVICES}


class BusinessServiceItem(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    category: str


class BusinessServicesSelectionRequest(BaseModel):
    selected_services: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("selected_services", "selectedServices", "services"),
        description="Array of selected business service identifiers"
    )

    model_config = {
        "populate_by_name": True,
        "extra": "ignore"
    }


class BusinessServicesSelectionResponse(BaseModel):
    success: bool = True
    message: str = "Business services saved successfully."
    selected_services: List[str]
    selectedServices: List[str]
    services: List[BusinessServiceItem]
    service_details: Optional[List[BusinessServiceItem]] = None
    count: int


class BusinessServicesCatalogResponse(BaseModel):
    success: bool = True
    services: List[BusinessServiceItem]
    count: int

