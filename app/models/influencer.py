from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId

class Influencer(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str
    platform: str # Instagram, YouTube, etc.
    niche: str # Fashion, Tech, Food, etc.
    followers_count: int
    engagement_rate: float
    contact_email: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class InfluencerCampaign(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    business_id: str
    influencer_id: str
    status: str = "pending" # pending, accepted, active, completed
    ai_pitch_message: Optional[str] = None
    budget: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
