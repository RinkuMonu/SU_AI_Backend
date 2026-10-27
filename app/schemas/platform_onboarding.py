from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# Standard Marketplace platforms catalogue
SUPPORTED_MARKETPLACE_PLATFORMS: List[Dict[str, Any]] = [
    {"id": "amazon", "name": "Amazon", "icon": "shopping-bag", "category": "marketplace"},
    {"id": "flipkart", "name": "Flipkart", "icon": "shopping-cart", "category": "marketplace"},
    {"id": "meesho", "name": "Meesho", "icon": "store", "category": "marketplace"},
    {"id": "myntra", "name": "Myntra", "icon": "shirt", "category": "marketplace"},
    {"id": "nykaa", "name": "Nykaa", "icon": "sparkles", "category": "marketplace"},
    {"id": "jiomart", "name": "JioMart", "icon": "shopping-basket", "category": "marketplace"},
    {"id": "ajio", "name": "Ajio", "icon": "tag", "category": "marketplace"},
    {"id": "blinkit", "name": "Blinkit", "icon": "zap", "category": "marketplace"},
    {"id": "zepto", "name": "Zepto", "icon": "clock", "category": "marketplace"},
    {"id": "instamart", "name": "Swiggy Instamart", "icon": "package", "category": "marketplace"},
    {"id": "tata_1mg", "name": "Tata 1mg", "icon": "heart", "category": "marketplace"},
    {"id": "etsy", "name": "Etsy", "icon": "gift", "category": "marketplace"},
    {"id": "ebay", "name": "eBay", "icon": "globe", "category": "marketplace"},
    {"id": "shopify", "name": "Shopify Storefront", "icon": "layout", "category": "marketplace"},
    {"id": "woocommerce", "name": "WooCommerce Storefront", "icon": "box", "category": "marketplace"},
    {"id": "other", "name": "Other", "icon": "more-horizontal", "category": "marketplace"}
]

# Standard Wholesale / B2B directories catalogue
SUPPORTED_B2B_PLATFORMS: List[Dict[str, Any]] = [
    {"id": "indiamart", "name": "IndiaMART", "icon": "briefcase", "category": "directory"},
    {"id": "tradeindia", "name": "TradeIndia", "icon": "truck", "category": "directory"},
    {"id": "justdial", "name": "Justdial", "icon": "phone", "category": "directory"},
    {"id": "exportersindia", "name": "ExportersIndia", "icon": "globe", "category": "directory"},
    {"id": "udaan", "name": "Udaan", "category": "directory", "icon": "shopping-cart"},
    {"id": "alibaba", "name": "Alibaba", "icon": "building", "category": "directory"},
    {"id": "industrybuying", "name": "Industrybuying", "icon": "tool", "category": "directory"},
    {"id": "power2sme", "name": "Power2SME", "icon": "shield", "category": "directory"},
    {"id": "none_of_these", "name": "None of these", "icon": "x-circle", "category": "directory", "is_none_option": True},
    {"id": "other", "name": "Other", "icon": "more-horizontal", "category": "directory"}
]

MARKETPLACE_NAME_MAP = {p["id"]: p["name"] for p in SUPPORTED_MARKETPLACE_PLATFORMS}
B2B_NAME_MAP = {p["id"]: p["name"] for p in SUPPORTED_B2B_PLATFORMS}


class PlatformItem(BaseModel):
    id: str = Field(..., description="Normalized platform identifier (e.g. amazon, indiamart, other)")
    name: str = Field(..., description="Display name of the platform")
    category: str = Field(default="marketplace", description="marketplace | directory | other")
    is_custom: bool = Field(default=False, description="Whether this is a user-defined custom platform")
    url: Optional[str] = Field(default=None, description="Optional profile or product listing URL on this platform")
    analysis_status: Optional[str] = Field(default=None, description="Status of URL analysis: pending | completed | failed | skipped")
    error: Optional[str] = Field(default=None, description="Optional error message if URL analysis failed")


class PlatformCatalogItem(BaseModel):
    id: str
    name: str
    icon: Optional[str] = "grid"
    category: str
    is_none_option: bool = False


class PlatformCatalogResponse(BaseModel):
    success: bool = True
    onboarding_source: str
    platforms: List[PlatformCatalogItem]


class SavePlatformsRequest(BaseModel):
    onboarding_source: Optional[str] = Field(
        None,
        description="Onboarding source: 'marketplace_seller' or 'wholesale_b2b'"
    )
    selected_platforms: List[str] = Field(
        ...,
        min_length=1,
        description="List of selected platform identifiers or names"
    )
    custom_platform_name: Optional[str] = Field(
        None,
        description="Required custom platform name when 'other' is selected"
    )
    other_platform_name: Optional[str] = Field(
        None,
        description="Alias for custom_platform_name"
    )
    website_url: Optional[str] = Field(
        None,
        description="Optional website/storefront URL"
    )
    skip_website: Optional[bool] = Field(
        False,
        description="Whether to skip website analysis and proceed to manual details"
    )
    platform_urls: Optional[Dict[str, str]] = Field(
        default=None,
        description="Map of platform IDs or names to storefront / profile URLs"
    )
    urls: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Optional array of platform URL mappings [{'platform': 'amazon', 'url': '...'}]"
    )

    @field_validator("selected_platforms")
    @classmethod
    def validate_selected_platforms(cls, v: List[str]) -> List[str]:
        if not v or not isinstance(v, list):
            raise ValueError("selected_platforms must be a non-empty array of platform names or IDs.")
        cleaned = [str(p).strip() for p in v if p and str(p).strip()]
        if not cleaned:
            raise ValueError("selected_platforms must contain at least one valid platform.")
        return cleaned


class PlatformUrlAnalysisRequest(BaseModel):
    platform_id: str = Field(..., description="Platform identifier (e.g. amazon, indiamart)")
    url: str = Field(..., description="Storefront or listing URL on the platform")
    onboarding_source: Optional[str] = Field(None, description="marketplace_seller | wholesale_b2b")


class PlatformUrlAnalysisResponse(BaseModel):
    success: bool = True
    platform_id: str
    url: str
    status: str = Field(..., description="pending | completed | failed | skipped")
    job_id: Optional[str] = None
    error: Optional[str] = None
    discovered_images: List[str] = Field(default_factory=list)
    message: str = "Platform URL processed."


class PlatformOnboardingState(BaseModel):
    success: bool = True
    onboarding_source: str
    selected_platforms: List[str] = Field(default_factory=list)
    platform_details: List[PlatformItem] = Field(default_factory=list)
    custom_platform_name: Optional[str] = None
    none_of_these_selected: bool = False
    website_url: Optional[str] = None
    website_skipped: bool = False
    has_storefront: bool = False
    platform_urls: Dict[str, str] = Field(default_factory=dict)
    platform_analysis_status: Dict[str, str] = Field(default_factory=dict)
    platform_analysis_results: Dict[str, Any] = Field(default_factory=dict)
    source_images: List[str] = Field(default_factory=list)
    analysis_job_id: Optional[str] = None
    analysis_status: Optional[str] = None
    extracted_details: Optional[Dict[str, Any]] = None
    onboarding_step: int = 2
    onboarding_status: str = "in_progress"
    next_step: str = "website_or_profile"
    updated_at: Optional[datetime] = None


class PlatformWebsiteSubmissionRequest(BaseModel):
    website_url: Optional[str] = Field(None, description="Optional store/website URL to analyze")
    skip: bool = Field(default=False, description="Whether to skip entering a URL")


class PlatformWebsiteSubmissionResponse(BaseModel):
    success: bool = True
    skipped: bool = False
    website_url: Optional[str] = None
    job_id: Optional[str] = None
    analysis_status: Optional[str] = None
    message: str
    state: Optional[PlatformOnboardingState] = None

