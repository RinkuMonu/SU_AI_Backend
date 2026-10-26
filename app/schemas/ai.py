from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class CaptionRequest(BaseModel):
    product_id: Optional[str] = None
    objective: Optional[str] = "engagement"
    tone: Optional[str] = "professional"
    language: Optional[str] = "en"
    offer: Optional[str] = ""
    cta: Optional[str] = ""
    custom_topic: Optional[str] = None


class CaptionResponse(BaseModel):
    caption: str
    hashtags: List[str]
    cta: str


class AIGenerationHistoryResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    id: str
    user_id: str
    business_id: str
    generation_type: str
    provider: str
    model_name: str
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    status: str
    execution_time_ms: int
    created_at: str


class ImageGenerationRequest(BaseModel):
    prompt: str
    product_id: Optional[str] = None
    reference_images: Optional[List[str]] = Field(default_factory=list)
    additional_instruction: Optional[str] = None


# ============================================================================
# Advanced Marketing Intelligence Schemas
# ============================================================================

class CompetitorAnalysisRequest(BaseModel):
    industry: Optional[str] = None
    competitors: Optional[List[str]] = Field(default_factory=list)
    target_market: Optional[str] = None
    specific_questions: Optional[str] = None


class CompetitorDirectItem(BaseModel):
    name: str
    positioning: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)


class SWOTAnalysis(BaseModel):
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    opportunities: List[str] = Field(default_factory=list)
    threats: List[str] = Field(default_factory=list)


class CompetitorAnalysisResponse(BaseModel):
    market_overview: str
    key_competitor_types: List[str] = Field(default_factory=list)
    direct_competitors: List[CompetitorDirectItem] = Field(default_factory=list)
    swot_analysis: SWOTAnalysis
    differentiator_strategy: List[str] = Field(default_factory=list)
    actionable_tactics: List[str] = Field(default_factory=list)


class WebsiteAnalysisRequest(BaseModel):
    website_url: Optional[str] = None
    primary_goal: Optional[str] = "leads_and_sales"
    target_audience: Optional[str] = None


class WebsiteAnalysisResponse(BaseModel):
    website_url: Optional[str] = None
    overall_health_score: int = 80
    brand_messaging_clarity: str
    conversion_funnel_audit: Dict[str, Any] = Field(default_factory=dict)
    seo_and_content_recommendations: Dict[str, Any] = Field(default_factory=dict)
    actionable_next_steps: List[str] = Field(default_factory=list)


class SocialTrendAnalysisRequest(BaseModel):
    platform: Optional[str] = "instagram"
    industry: Optional[str] = None
    timeframe: Optional[str] = "current"


class SocialTrendAnalysisResponse(BaseModel):
    platform: str
    industry: str
    current_viral_formats: List[str] = Field(default_factory=list)
    trending_hooks: List[str] = Field(default_factory=list)
    sound_and_audio_guidance: str
    hashtag_strategy: Dict[str, List[str]] = Field(default_factory=dict)
    content_calendar_ideas: List[Dict[str, Any]] = Field(default_factory=list)


class ProductMarketingRequest(BaseModel):
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    product_category: Optional[str] = None
    product_features: Optional[List[str]] = Field(default_factory=list)
    target_audience: Optional[str] = None


class ProductMarketingResponse(BaseModel):
    product_name: str
    target_buyer_persona: Dict[str, Any] = Field(default_factory=dict)
    unique_selling_propositions: List[str] = Field(default_factory=list)
    value_proposition: str
    marketing_copy_variations: Dict[str, str] = Field(default_factory=dict)


class BrandStrategyRequest(BaseModel):
    business_id: Optional[str] = None
    focus_area: Optional[str] = "complete_strategy"


class BrandStrategyResponse(BaseModel):
    brand_name: str
    voice_guidelines: Dict[str, Any] = Field(default_factory=dict)
    color_and_visual_strategy: Dict[str, Any] = Field(default_factory=dict)
    content_pillars: List[Dict[str, Any]] = Field(default_factory=list)
    growth_recommendations: List[str] = Field(default_factory=list)
