from pydantic import Field, AliasChoices
from typing import Optional, List
from app.models.base import MongoBaseModel

class Business(MongoBaseModel):
    ownerId: str = Field(default="", validation_alias=AliasChoices("ownerId", "owner_id", "userId", "user_id"))
    businessName: str = Field(default="My Business", validation_alias=AliasChoices("businessName", "business_name", "name"))
    businessType: str = Field(default="Retail", validation_alias=AliasChoices("businessType", "business_type", "type"))
    industry: str = Field(default="General", validation_alias=AliasChoices("industry", "category"))
    website: Optional[str] = None
    logoUrl: Optional[str] = Field(default=None, validation_alias=AliasChoices("logoUrl", "logo_url"))
    brandColors: Optional[List[str]] = Field(default=None, validation_alias=AliasChoices("brandColors", "brand_colors"))
    preferredLanguage: Optional[str] = Field(default=None, validation_alias=AliasChoices("preferredLanguage", "preferred_language", "language"))
    targetAudience: Optional[str] = Field(default=None, validation_alias=AliasChoices("targetAudience", "target_audience", "target_customer"))
    primaryGoal: Optional[str] = Field(default=None, validation_alias=AliasChoices("primaryGoal", "primary_goal", "brand_tone"))

    @property
    def name(self) -> str:
        return self.businessName

    @property
    def owner_id(self) -> str:
        return self.ownerId
