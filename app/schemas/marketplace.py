from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- DISCOVERY SCHEMAS ---
class InfluencerFilterParams(BaseModel):
    search: Optional[str] = None
    platform: Optional[str] = None
    min_followers: Optional[int] = None
    max_followers: Optional[int] = None
    location: Optional[str] = None
    niche: Optional[str] = None
    min_engagement: Optional[float] = None
    is_verified: Optional[bool] = None
    sort_by: Optional[str] = "followers_desc"  # followers_desc, engagement_desc, newest
    page: int = 1
    limit: int = 12

class InfluencerSocialPlatform(BaseModel):
    platform: str
    username: Optional[str] = None
    url: Optional[str] = None
    followers: int = 0
    engagement_rate: Optional[float] = 0.0

class InfluencerProfileMarketplace(BaseModel):
    id: str
    user_id: Optional[str] = None
    fullName: str
    username: str
    email: Optional[str] = None
    niche: str
    category: str
    bio: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "India"
    location: str
    profile_image: Optional[str] = None
    is_verified: bool = False
    follower_count: int = 0
    engagement_rate: float = 0.0
    expectedPricePerPost: Optional[float] = 0.0
    connected_platforms: List[str] = []
    platforms_data: List[InfluencerSocialPlatform] = []
    collaboration_info: Optional[str] = None

# --- HIRING SCHEMAS ---
class HiringRequestCreate(BaseModel):
    influencer_id: str = Field(..., description="Target Influencer Profile or User ID")
    campaign_name: str = Field(..., min_length=3, description="Campaign title")
    product_or_service: str = Field(..., description="Brand product or service being promoted")
    campaign_objectives: str = Field(..., description="Goals: brand awareness, conversions, UGC")
    deliverables: List[str] = Field(..., min_items=1, description="e.g. 1 Instagram Reel, 2 Stories")
    social_platform: str = Field(default="Instagram", description="Target platform")
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    proposed_compensation: float = Field(..., gt=0, description="Agreed creator fee in INR")
    revision_requirements: Optional[str] = "Up to 2 creative revisions included."
    special_instructions: Optional[str] = None

class HiringRequestRespond(BaseModel):
    action: str = Field(..., pattern="^(accept|reject)$", description="accept or reject")
    note: Optional[str] = None

# --- AGREEMENT SCHEMAS ---
class AgreementSignRequest(BaseModel):
    signer_name: str = Field(..., min_length=2, description="Signer full legal name")
    declaration_accepted: bool = Field(..., description="Must confirm agreement terms acceptance")
    signer_title: Optional[str] = "Authorized Signatory"

# --- PAYMENT SCHEMAS ---
class PlatformFeeConfig(BaseModel):
    service_fee: float = 199.0
    currency: str = "INR"
    tax_percentage: float = 18.0
    tax_amount: float = 35.82
    total_fee: float = 234.82
    fee_description: str = "Platform Escrow & Verified Collaboration Fee"

class PaymentCreateOrderRequest(BaseModel):
    notes: Optional[str] = None

class PaymentVerifyRequest(BaseModel):
    order_id: str
    payment_id: Optional[str] = None
    signature: Optional[str] = None

# --- CHAT & MESSAGING SCHEMAS ---
class MarketplaceMessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=3000)
    attachments: Optional[List[Dict[str, Any]]] = None

# --- DELIVERABLES & REVIEW SCHEMAS ---
class DeliverablesSubmitRequest(BaseModel):
    live_links: List[str] = Field(default=[], description="URLs to published reels, posts, or stories")
    attachments: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None

class DeliverablesReviewRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|request_revision|dispute)$")
    review_notes: Optional[str] = None
    dispute_reason: Optional[str] = None

# --- ADMIN SCHEMAS ---
class AdminDisputeResolveRequest(BaseModel):
    action: str = Field(..., pattern="^(favor_hirer|favor_influencer|mutual_cancel)$")
    resolution_notes: str
