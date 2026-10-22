from typing import Optional, List
from datetime import datetime
from app.models.base import MongoBaseModel

class Business(MongoBaseModel):
    owner_id: str
    name: str
    category: str
    location: str
    business_type: Optional[str] = None
    registration_number: Optional[str] = None
    business_model: Optional[str] = None
    selling_model: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    target_customer: Optional[str] = None
    preferred_language: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    description: Optional[str] = None
    brand_kit_status: str = "not_started"
    brand_kit_completed: bool = False
    brand_kit_completed_at: Optional[datetime] = None
    social_connectivity_completed: bool = False
    social_connectivity_completed_at: Optional[datetime] = None
    connected_platforms: Optional[List[str]] = []
    plan_activation_completed: bool = False
    plan_activation_completed_at: Optional[datetime] = None
    active_plan_id: Optional[str] = None
    billing_cycle: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

