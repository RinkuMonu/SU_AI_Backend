from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

class CampaignApplication(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    campaign_id: str
    influencer_id: str  # maps to the user_id of the influencer
    business_id: str
    message: str
    proposed_price: Optional[float] = None
    status: str = "pending"  # pending, accepted, rejected, withdrawn
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
