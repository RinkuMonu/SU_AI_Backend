from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

class InfluencerEarning(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    influencer_id: str
    campaign_id: str
    collaboration_id: str
    business_name: Optional[str] = None
    campaign_name: Optional[str] = None
    amount: float
    status: str = "pending"  # pending, approved, paid, cancelled
    paid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
