from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone

class Collaboration(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    campaign_id: str
    business_id: str
    influencer_id: str
    application_id: str
    
    # Contract details
    agreed_price: float = 0.0
    deliverables: List[str] = Field(default_factory=list)
    status: str = "active"  # active, content_submitted, revision_requested, approved, published, completed, cancelled
    
    start_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
