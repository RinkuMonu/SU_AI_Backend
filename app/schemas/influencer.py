from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class InfluencerProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    category: Optional[str] = None
    niche: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    preferredLanguage: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    facebook_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    follower_count: Optional[int] = None
    engagement_rate: Optional[float] = None
    expectedPricePerPost: Optional[float] = None
    profile_image: Optional[str] = None

class InfluencerProfileResponse(BaseModel):
    id: str
    user_id: str
    fullName: str
    username: str
    email: str
    phone: Optional[str] = None
    bio: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    preferredLanguage: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    follower_count: int = 0
    engagement_rate: float = 0.0
    expectedPricePerPost: Optional[float] = None
    profile_image: Optional[str] = None
    profile_completion: int = 0
    is_social_connected: bool = False
    connected_platforms: List[str] = Field(default_factory=list)

class OpportunityBusinessInfo(BaseModel):
    id: str
    name: str
    logo: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

class OpportunityCampaignInfo(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    niche: List[str] = Field(default_factory=list)
    platforms: List[str] = Field(default_factory=list)
    collaboration_type: str = "Paid"
    budget: Optional[float] = None
    budget_display: Optional[str] = None
    duration: Optional[str] = None
    target_audience: Optional[str] = None
    deliverables: List[str] = Field(default_factory=list)
    status: str = "active"
    created_at: Optional[datetime] = None

class OpportunityItem(BaseModel):
    id: str
    business: OpportunityBusinessInfo
    campaign: OpportunityCampaignInfo
    is_applied: bool = False
    application_status: Optional[str] = None

class OpportunitiesPagination(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int

class OpportunitiesResponse(BaseModel):
    items: List[OpportunityItem]
    pagination: OpportunitiesPagination

class DashboardSummaryResponse(BaseModel):
    available_opportunities: int = 0
    new_opportunities: int = 0
    active_collaborations: int = 0
    completed_collaborations: int = 0
    total_earnings: float = 0.0

class ApplyOpportunityRequest(BaseModel):
    pitch_message: str = Field(..., min_length=5)
    proposed_budget: Optional[float] = None
    deliverables: Optional[List[str]] = None
