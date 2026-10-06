from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

class InfluencerShortlist(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    business_id: str
    influencer_id: str
    match_score: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
