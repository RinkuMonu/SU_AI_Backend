from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator


class GoogleMapsSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300, description="Shop or business name, or search query")
    latitude: Optional[float] = Field(None, description="Optional latitude for location bias")
    longitude: Optional[float] = Field(None, description="Optional longitude for location bias")
    radius: Optional[float] = Field(default=50000.0, description="Search radius in meters")


class GoogleMapsUrlResolveRequest(BaseModel):
    url: str = Field(..., min_length=5, description="Google Maps share link or web URL")


class GoogleMapsPlaceItem(BaseModel):
    place_id: str = Field(..., description="Google Place ID")
    business_name: str = Field(..., description="Business name")
    formatted_address: str = Field(..., description="Formatted full address")
    latitude: Optional[float] = Field(None, description="Latitude")
    longitude: Optional[float] = Field(None, description="Longitude")
    rating: Optional[float] = Field(None, description="Average user rating")
    review_count: Optional[int] = Field(None, description="Total review count")
    website: Optional[str] = Field(None, description="Website URL if available")
    phone_number: Optional[str] = Field(None, description="Contact phone number if available")
    city: Optional[str] = Field(None, description="Extracted city")
    state: Optional[str] = Field(None, description="Extracted state / province")
    country: Optional[str] = Field(None, description="Extracted country")
    postal_code: Optional[str] = Field(None, description="Postal / ZIP code")
    types: List[str] = Field(default_factory=list, description="Google Place types")
    photo_references: List[str] = Field(default_factory=list, description="Google photo resource names")
    photos: List[str] = Field(default_factory=list, description="Public photo URLs")
    google_maps_url: Optional[str] = Field(None, description="Google Maps web URL")


class GoogleMapsSearchResponse(BaseModel):
    success: bool = True
    total: int = 0
    query: str
    places: List[GoogleMapsPlaceItem] = Field(default_factory=list)


class GoogleMapsResolveResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    place: Optional[GoogleMapsPlaceItem] = None
    resolved_query: Optional[str] = None


class SelectGoogleMapsBusinessRequest(BaseModel):
    place_id: str = Field(..., min_length=5, description="Google Place ID")
    business_name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    website: Optional[str] = None
    phone_number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    types: Optional[List[str]] = None
    photos: Optional[List[str]] = None
    google_maps_url: Optional[str] = None


class GoogleMapsWebsiteRequest(BaseModel):
    website_url: Optional[str] = Field(None, description="HTTP/HTTPS website URL")
    skip: bool = Field(default=False, description="Whether to skip entering a website")

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        clean = v.strip()
        if not clean.lower().startswith("http://") and not clean.lower().startswith("https://"):
            clean = f"https://{clean}"
        return clean


class GoogleMapsCategoryRequest(BaseModel):
    category: str = Field(..., min_length=2, description="Selected business category")
    sub_category: Optional[str] = Field(None, description="Selected business subcategory")
    custom_category: Optional[str] = Field(None, description="Custom category if applicable")
    custom_subcategory: Optional[str] = Field(None, description="Custom subcategory if applicable")


class GoogleMapsProfileRequest(BaseModel):
    business_name: str = Field(..., min_length=1, description="Business name")
    promotion_goal: str = Field(..., min_length=2, description="What should we promote? (Required)")
    target_audience: Optional[str] = Field(None, description="Target customer group")
    differentiators: Optional[List[str]] = Field(default=None, description="USPs / Differentiators")
    logo_url: Optional[str] = Field(None, description="Uploaded logo asset URL")
    tagline: Optional[str] = Field(None, description="Tagline or slogan")
    products_services: Optional[List[str]] = Field(default=None, description="Key products or services")


class GoogleMapsPhotoItem(BaseModel):
    url: str = Field(..., description="Public image URL")
    alt: Optional[str] = Field(None, description="Descriptive alt label")
    type: str = Field(default="google_maps", description="google_maps | user_upload | logo")
    source: str = Field(default="google_maps", description="google_maps | user_upload")
    selected: bool = Field(default=False, description="Whether selected by the user")
    width: Optional[int] = None
    height: Optional[int] = None


class GoogleMapsPhotosResponse(BaseModel):
    success: bool = True
    photos: List[GoogleMapsPhotoItem] = Field(default_factory=list)
    selected_photo_urls: List[str] = Field(default_factory=list)
    max_selection_limit: int = 15
    total_photos: int = 0
    selected_count: int = 0


class SelectGoogleMapsPhotosRequest(BaseModel):
    selected_photo_urls: List[str] = Field(default_factory=list, description="Array of selected photo URLs")


class GoogleMapsOnboardingState(BaseModel):
    success: bool = True
    current_step: str = Field(default="business_select", description="business_select | website | category | profile | photos | completed")
    onboarding_step_number: int = Field(default=1, description="1 to 5")
    is_completed: bool = False
    selected_business: Optional[GoogleMapsPlaceItem] = None
    website: Optional[str] = None
    website_skipped: bool = False
    category: Optional[str] = None
    sub_category: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None
    photos: List[GoogleMapsPhotoItem] = Field(default_factory=list)
    selected_photo_urls: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GoogleMapsOnboardingCompleteResponse(BaseModel):
    success: bool = True
    message: str = "Google Maps onboarding completed successfully."
    next_step: str = "social_connectivity"
    onboarding_route: str = "/onboarding?step=social_connectivity"
    business: Dict[str, Any] = Field(default_factory=dict)
    brand_kit: Dict[str, Any] = Field(default_factory=dict)
