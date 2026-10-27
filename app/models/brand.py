from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.base import MongoBaseModel

class BrandKit(MongoBaseModel):
    business_id: str
    owner_id: Optional[str] = None
    brand_name: Optional[str] = None
    business_name: Optional[str] = None
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
    gradient: Optional[Dict[str, Any]] = None
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
    palette: Optional[List[str]] = None
    brand_colors: Optional[List[str]] = None
    tones: Optional[List[str]] = None
    business_types: Optional[List[str]] = None
    primary_business_type: Optional[str] = None
    sub_category: Optional[str] = None
    city: Optional[str] = None
    differentiators: Optional[List[str]] = None
    products_services: Optional[List[str]] = None
    selected_photos: Optional[List[str]] = None
    target_audience_summary: Optional[str] = None
    services_products_summary: Optional[List[str]] = None
    generating_for: Optional[List[str]] = None
    online_presence: Optional[str] = None
    brand_kit_status: str = "not_started"
    brand_kit_completed: bool = False
    brand_kit_completed_at: Optional[datetime] = None
    completion_percentage: int = 0
    completed_sections: List[str] = []
    pending_sections: List[str] = []
    brand_kit_dismissed: bool = False
    partial_saved: bool = False
    is_draft: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

