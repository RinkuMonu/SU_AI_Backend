from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from datetime import datetime

class CampaignAsset(BaseModel):
    id: str
    type: str  # "post", "reel", "ad", "story"
    platform: str  # "instagram", "facebook", "linkedin"
    content: Dict[str, Any]  # e.g., {"text": "Happy Diwali!", "image_prompt": "..."}
    scheduled_date: str  # ISO string or relative day

class FestivalCampaign(BaseModel):
    id: Optional[str] = None
    business_id: str
    festival_name: str
    festival_date: str
    status: str = Field(default="draft")  # "draft", "approved", "active"
    offer_strategy: str
    assets: List[CampaignAsset]
    created_at: datetime = Field(default_factory=datetime.utcnow)
