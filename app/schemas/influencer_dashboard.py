from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class CreatorProfileSummary(BaseModel):
    user_id: str
    full_name: str = ""
    username: str = ""
    profile_image: str = ""
    bio: str = ""
    primary_niche: str = ""
    location: str = "India"
    gender: str = ""
    verification_status: str = "UNVERIFIED"  # UNVERIFIED, PENDING, VERIFIED
    social_accounts: Dict[str, Any] = Field(default_factory=dict)
    connected_platforms: List[str] = Field(default_factory=list)

class DealSummary(BaseModel):
    id: str
    title: str
    business_name: str
    business_category: Optional[str] = None
    business_logo: Optional[str] = None
    business_location: Optional[str] = None
    budget: float = 0.0
    budget_display: str = ""
    status: str = "active"
    deadline: Optional[str] = None
    collaboration_type: str = "Paid"

class BrandOfferSummary(BaseModel):
    id: str
    title: str
    business_id: Optional[str] = None
    business_name: str
    business_category: Optional[str] = None
    business_logo: Optional[str] = None
    business_location: Optional[str] = None
    niche: List[str] = Field(default_factory=list)
    budget: float = 0.0
    budget_display: str = ""
    platforms: List[str] = Field(default_factory=list)
    duration: Optional[str] = None
    deliverables: List[str] = Field(default_factory=list)
    collaboration_type: str = "Paid"
    is_applied: bool = False
    application_status: Optional[str] = None

class EarningsSummary(BaseModel):
    total_earnings: float = 0.0
    pending_payout: float = 0.0
    completed_deals_count: int = 0
    currency: str = "INR"

class PerformanceMetrics(BaseModel):
    total_reach: int = 0
    engagement_rate: float = 0.0
    completed_collaborations: int = 0
    active_collaborations: int = 0
    acceptance_rate: float = 0.0

class RecentActivityItem(BaseModel):
    id: str
    activity_type: str  # deal_applied, deal_accepted, message_received, payment_received, collaboration_requested
    title: str
    description: str
    timestamp: str
    meta: Dict[str, Any] = Field(default_factory=dict)

class InfluencerDashboardData(BaseModel):
    profile: CreatorProfileSummary
    verification_status: str = "UNVERIFIED"
    social_account_status: Dict[str, Any] = Field(default_factory=dict)
    profile_completion: int = 0
    active_collaborations_count: int = 0
    collaboration_requests_count: int = 0
    earnings: EarningsSummary
    recommended_business_opportunities: List[BrandOfferSummary] = Field(default_factory=list)
    available_brand_offers: List[BrandOfferSummary] = Field(default_factory=list)
    active_collaborations: List[DealSummary] = Field(default_factory=list)
    active_deals: List[DealSummary] = Field(default_factory=list)
    performance_metrics: PerformanceMetrics
    recent_activity: List[RecentActivityItem] = Field(default_factory=list)
    unread_chat_count: int = 0
    unread_message_count: int = 0

class InfluencerDashboardResponse(BaseModel):
    success: bool = True
    data: InfluencerDashboardData
