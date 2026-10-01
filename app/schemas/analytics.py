"""
Analytics response schemas for GET /api/v1/analytics/overview.

All models use explicit types; no dynamic or unvalidated fields.
External metrics are typed as Optional[int] because the required
social integrations (Instagram, Facebook, WhatsApp) do not exist yet.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class ContentAnalytics(BaseModel):
    """Counts of user-created content items within the selected date range."""
    posts: int = 0
    reels: int = 0
    images: int = 0
    photoshoots: int = 0
    captions: int = 0


class AIUsageAnalytics(BaseModel):
    """AI generation usage within the selected date range."""
    total_generations: int = 0
    post_generations: int = 0
    image_generations: int = 0
    photoshoot_generations: int = 0
    reel_generations: int = 0
    credits_used: int = 0


class BusinessAnalytics(BaseModel):
    Business-related analytics.

    products: Current catalogue size (NOT date-filtered).
    """
    products: int = 0


class ExternalAnalytics(BaseModel):
    """
    External platform metrics.

    status values:
      - "instagram"   → fetched from real Instagram Graph API
      - "facebook"    → fetched from real Facebook Graph API
      - "estimated"   → intelligently estimated from internal activity data
      - "not_connected" → no data available at all

    reach, engagement etc. are None only when status="not_connected".
    """
    reach: Optional[int] = None
    engagement: Optional[int] = None
    leads: Optional[int] = None
    whatsapp_enquiries: Optional[int] = None
    followers: Optional[int] = None
    impressions: Optional[int] = None
    status: str = "not_connected"
    last_synced: Optional[str] = None


class DailyActivity(BaseModel):
    """
    One bucket per calendar day in the selected range.

    Zero-activity days are included with zeroes — never omitted.
    ``ai_generations`` is the total AI operations for that day
    (posts + reels + images + photoshoots + captions).
    """
    date: str
    posts: int = 0
    reels: int = 0
    ai_generations: int = 0


class MarketingScoreBreakdown(BaseModel):
    """Individual components of the marketing score."""
    content_activity: int = 0
    ai_usage: int = 0
    product_catalogue: int = 0
    reel_activity: int = 0


class MarketingScore(BaseModel):
    """
    Deterministic 0–100 score derived from real internal activity.

    This does NOT represent external social-media performance.

    Formula (documented in ``formula`` field):
        content_activity  = min(posts_in_range * 5, 25)
        ai_usage          = min(total_generations_in_range * 2, 25)
        product_catalogue = min(current_product_count * 5, 20)
        reel_activity     = min(reels_in_range * 5, 15)
        score             = min(sum, 100)
    """
    score: int = 0
    breakdown: MarketingScoreBreakdown = MarketingScoreBreakdown()
    formula: str = (
        "content_activity = min(posts_in_range * 5, 25); "
        "ai_usage = min(total_generations_in_range * 2, 25); "
        "product_catalogue = min(current_product_count * 5, 20); "
        "reel_activity = min(reels_in_range * 5, 15); "
        "score = min(sum, 100)"
    )


class Recommendation(BaseModel):
    A deterministic recommendation that varies based on actual user data.

    ``type`` indicates the area the recommendation targets, e.g.
    "content", "reels", "products", "photoshoots",
    "images", or "general".
    """
    text: str
    type: str


class AnalyticsPeriod(BaseModel):
    """UTC start/end timestamps of the analytics window."""
    start: str
    end: str


class AnalyticsOverviewResponse(BaseModel):
    """Top-level response for GET /api/v1/analytics/overview."""
    success: bool = True
    data: "AnalyticsData"


class AnalyticsData(BaseModel):
    """Inner data payload of the analytics response."""
    range: str = Field(..., description="The requested date range (7d, 30d, 90d)")
    period: AnalyticsPeriod
    content: ContentAnalytics
    ai_usage: AIUsageAnalytics
    business: BusinessAnalytics
    activity: List[DailyActivity]
    external: ExternalAnalytics
    marketing_score: MarketingScore
    recommendation: Recommendation

    model_config = {"populate_by_name": True}
