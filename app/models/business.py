from typing import Optional, List
from datetime import datetime
from pydantic import Field, AliasChoices
from app.models.base import MongoBaseModel

class Business(MongoBaseModel):
    owner_id: str = Field(default="", validation_alias=AliasChoices("owner_id", "ownerId", "userId", "user_id"))
    name: str = Field(default="My Business", validation_alias=AliasChoices("name", "businessName", "business_name"))
    category: str = Field(default="General", validation_alias=AliasChoices("category", "industry"))
    location: str = "India"
    business_type: Optional[str] = Field(default=None, validation_alias=AliasChoices("business_type", "businessType", "type"))
    registration_number: Optional[str] = None
    business_model: Optional[str] = None
    selling_model: Optional[str] = None
    website: Optional[str] = None
    instagram: Optional[str] = None
    target_customer: Optional[str] = Field(default=None, validation_alias=AliasChoices("target_customer", "targetCustomer", "targetAudience"))
    preferred_language: Optional[str] = Field(default=None, validation_alias=AliasChoices("preferred_language", "preferredLanguage", "language"))
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("logo_url", "logoUrl"))
    brand_colors: Optional[List[str]] = Field(default=None, validation_alias=AliasChoices("brand_colors", "brandColors"))
    primary_goal: Optional[str] = Field(default=None, validation_alias=AliasChoices("primary_goal", "primaryGoal", "brand_tone"))

    # Onboarding Status Fields
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

    @property
    def ownerId(self) -> str:
        return self.owner_id

    @property
    def businessName(self) -> str:
        return self.name
