from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class BusinessProfile(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    presence_types: List[str] = Field(default_factory=list)
    links: List[Dict[str, Any]] = Field(default_factory=list)
    extracted_draft: Optional[Dict[str, Any]] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    business_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    photos: List[Dict[str, Any]] = Field(default_factory=list)
    social_accounts: List[Dict[str, Any]] = Field(default_factory=list)
    ai_photos: Optional[Dict[str, Any]] = None
    rating: Optional[Dict[str, Any]] = None
    subscription_plan: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
