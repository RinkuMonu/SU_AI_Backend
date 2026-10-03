from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

class ContentSubmission(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    collaboration_id: str
    influencer_id: str
    business_id: str
    content_type: str  # e.g., image, video, document
    media_url: str
    caption: Optional[str] = None
    hashtags: Optional[str] = None
    platform: Optional[str] = None
    
    # Workflow status
    status: str = "pending_review"  # pending_review, changes_requested, approved, published
    feedback: Optional[str] = None
    live_url: Optional[str] = None
    
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
