from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Constants from UI/UX reference screenshots
VALID_BUSINESS_TYPES = [
    "Product-based",
    "Physical Location",
    "Service / Digital"
]

VALID_BRAND_TONES = [
    "Modern", "Trendy", "Youthful", "Bold",
    "Luxurious", "Fun", "Professional", "Minimal",
    "Traditional", "Warm", "Energetic", "Elegant",
    "Festive", "Desi", "Premium", "Budget-friendly"
]

VALID_CONTENT_LANGUAGES = [
    "Hindi", "English", "Hinglish", "Tamil", "Telugu",
    "Bengali", "Marathi", "Kannada", "Gujarati", "Malayalam"
]


class WebsiteAnalysisCreateRequest(BaseModel):
    url: Optional[str] = Field(None, description="Target website URL to analyze")
    website_url: Optional[str] = Field(None, description="Alias for website URL")
    website: Optional[str] = Field(None, description="Alias for website URL")
    onboarding_type: Optional[str] = Field("website", description="Selected onboarding type")
    business_name: Optional[str] = Field(None, description="Optional business name")

    def get_url(self) -> str:
        raw = self.url or self.website_url or self.website
        if not raw or not str(raw).strip():
            raise ValueError("Website URL is required.")
        return str(raw).strip()


class BusinessDetails(BaseModel):
    business_name: str = Field(..., description="Business name")
    category: str = Field("General", description="Primary business category (e.g. Tech & Electronics)")
    business_types: List[str] = Field(default_factory=list, description="Selected business types: Product-based, Physical Location, Service / Digital")
    primary_business_type: Optional[str] = Field(None, description="Primary business type (e.g. Service / Digital)")
    sub_category: Optional[str] = Field(None, description="Optional sub-category (e.g. Software Development)")
    city: Optional[str] = Field(None, description="City / Location (e.g. Jaipur, India)")
    logo_url: Optional[str] = Field(None, description="Business logo image URL")
    tagline: Optional[str] = Field(None, description="Optional tagline or brand statement")
    target_audience: Optional[str] = Field(None, description="Who buys from you (target audience description)")
    differentiators: List[str] = Field(default_factory=list, description="Dynamic list of differentiators / USPs")
    products_services: List[str] = Field(default_factory=list, description="Dynamic list of products or services sold")


class BrandPreferences(BaseModel):
    tagline: Optional[str] = Field(None, description="Business tagline or brand statement in quote card")
    brand_colors: List[str] = Field(default_factory=list, description="Brand color palette (5 editable hex color codes)")
    tones: List[str] = Field(default_factory=list, description="Selected brand tones from the 16 reference options")
    default_language: str = Field("English", description="Default content language from the 10 reference options")
    target_audience_summary: Optional[str] = Field(None, description="Summary description of target audience")
    services_products_summary: List[str] = Field(default_factory=list, description="List/tags summarizing products and services")


class WebsitePhotoItem(BaseModel):
    url: str = Field(..., description="Absolute URL to the image")
    alt: Optional[str] = Field(None, description="Descriptive alt text")
    type: str = Field("photo", description="Image classification: logo, hero, product, gallery, user_upload")
    width: Optional[int] = Field(None, description="Width in pixels if known")
    height: Optional[int] = Field(None, description="Height in pixels if known")
    source_page: Optional[str] = Field(None, description="Source page or section")
    selected: bool = Field(False, description="Whether currently selected")


class PhotoItem(WebsitePhotoItem):
    """Backwards compatibility alias for PhotoItem"""
    pass


class StepStatuses(BaseModel):
    fetching: str = Field("pending", description="Status of HTML & asset fetching: pending, in_progress, completed, failed")
    brand_voice: str = Field("pending", description="Status of Brand Voice analysis")
    colors: str = Field("pending", description="Status of Colors analysis")
    category: str = Field("pending", description="Status of Category analysis")
    photos: str = Field("pending", description="Status of Photos analysis")


# Legacy compatibility results classes
class BrandVoiceResult(BaseModel):
    tone: str = Field(..., description="Brand voice and communication tone")
    tagline: Optional[str] = Field(None, description="Identified or suggested brand slogan")
    description: str = Field(..., description="Brand identity & mission summary")
    target_audience: Optional[str] = Field(None, description="Identified target audience profile")
    keywords: List[str] = Field(default_factory=list, description="Core keywords reflecting brand tone")


class BrandColorsResult(BaseModel):
    primary: str = Field(..., description="Primary brand hex color")
    secondary: str = Field(..., description="Secondary brand hex color")
    accent: str = Field(..., description="Accent / CTA brand hex color")
    palette: List[str] = Field(default_factory=list, description="Harmonized hex color palette")


class BrandCategoryResult(BaseModel):
    business_name: str = Field(..., description="Detected business or brand name")
    primary_category: str = Field(..., description="Main business category")
    sub_categories: List[str] = Field(default_factory=list, description="Specific sub-categories or tags")
    business_type: Optional[str] = Field(None, description="Business model")
    summary: Optional[str] = Field(None, description="Summary of the business category")


class WebsiteAnalysisResults(BaseModel):
    brand_voice: Optional[BrandVoiceResult] = None
    colors: Optional[BrandColorsResult] = None
    category: Optional[BrandCategoryResult] = None
    photos: List[WebsitePhotoItem] = Field(default_factory=list, description="Extracted photos and images")
    logo_url: Optional[str] = Field(None, description="Primary detected logo URL")
    hero_image: Optional[str] = Field(None, description="Main banner or hero image URL")
    website_title: Optional[str] = Field(None, description="Extracted page title")
    meta_description: Optional[str] = Field(None, description="Extracted meta description")
    # Extended reference fields
    business_details: Optional[BusinessDetails] = None
    brand_preferences: Optional[BrandPreferences] = None


class WebsiteAnalysisJobResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str = "pending"
    url: str
    onboarding_type: str = "website"
    created_at: datetime


class WebsiteAnalysisStatusResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str = Field(..., description="Current job status: pending, processing, completed, failed")
    progress: int = Field(0, description="Overall progress percentage 0-100")
    current_step: str = Field("fetching_website", description="Active step name")
    step_statuses: StepStatuses
    results: Optional[WebsiteAnalysisResults] = None
    url: str
    onboarding_type: str = "website"
    onboarding_step: str = Field("business_details", description="Active step: business_details, brand_preferences, website_photos, completed")
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CompleteWebsiteOnboardingProfile(BaseModel):
    success: bool = True
    job_id: str
    url: str
    status: str
    progress: int
    current_step: str
    step_statuses: StepStatuses
    business_details: BusinessDetails
    brand_preferences: BrandPreferences
    photos: List[WebsitePhotoItem]
    selected_photo_urls: List[str] = Field(default_factory=list)
    onboarding_step: str = "business_details"
    created_at: datetime
    updated_at: datetime


class WebsitePhotosResponse(BaseModel):
    success: bool = True
    job_id: str
    photos: List[WebsitePhotoItem] = Field(default_factory=list)
    selected_photo_urls: List[str] = Field(default_factory=list)
    max_selection_limit: int = 10
    total_discovered: int = 0
    selected_count: int = 0


class SaveWebsitePhotosRequest(BaseModel):
    selected_photo_urls: List[str] = Field(..., description="List of chosen photo URLs")


class ApplyWebsiteAnalysisResponse(BaseModel):
    success: bool = True
    message: str = "Website analysis successfully applied to brand kit and profile."
    job_id: str
    brand_kit: Optional[Dict[str, Any]] = None
    business: Optional[Dict[str, Any]] = None


class CompleteWebsiteOnboardingResponse(BaseModel):
    success: bool = True
    message: str = "Website onboarding completed successfully."
    job_id: str
    next_step: str = "social_connectivity"
    onboarding_route: str = "/onboarding?step=social_connectivity"
    business: Optional[Dict[str, Any]] = None
    brand_kit: Optional[Dict[str, Any]] = None
