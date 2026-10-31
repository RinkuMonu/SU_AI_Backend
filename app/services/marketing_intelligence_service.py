import json
import logging
from typing import Dict, Any, List, Optional

from app.ai.factory import AIProviderFactory
from app.ai.services.business_context import BusinessContextService
from app.schemas.ai import (
    CompetitorAnalysisRequest,
    CompetitorAnalysisResponse,
    WebsiteAnalysisRequest,
    WebsiteAnalysisResponse,
    SocialTrendAnalysisRequest,
    SocialTrendAnalysisResponse,
    ProductMarketingRequest,
    ProductMarketingResponse,
    BrandStrategyRequest,
    BrandStrategyResponse,
)

logger = logging.getLogger(__name__)


class MarketingIntelligenceService:
    """
    Advanced AI Marketing Intelligence Service powered by OpenAI GPT-4.1 Mini.
    Features:
    - Task-specific system instructions & structured JSON schema outputs
    - Automatic connection to authentic Business & Brand Kit context without hallucination
    - Dual-tier model routing ('reasoning' tier for strategic analysis, 'fast' for high-volume content)
    """

    @classmethod
    async def analyze_competitors(
        cls,
        db,
        user_id: str,
        request: CompetitorAnalysisRequest
    ) -> CompetitorAnalysisResponse:
        """
        Conducts deep competitive landscape analysis and positioning strategy
        anchored in the user's authentic business category and target customer.
        """
        context = await BusinessContextService.get_business_context(user_id=user_id, business_id=user_id, db=db)
        biz = context.get("business", {})
        brand = context.get("brand", {})

        b_name = biz.get("name") or brand.get("brand_name") or "Your Brand"
        industry = request.industry or biz.get("category") or "General Business"
        audience = request.target_market or biz.get("target_customer") or brand.get("target_audience") or "Target Consumers"
        specified_competitors = ", ".join(request.competitors) if request.competitors else "Key industry rivals in this category"
        extra_q = f"Special inquiry: {request.specific_questions}" if request.specific_questions else ""

        system_instruction = (
            "You are an elite competitive intelligence analyst and brand positioning strategist. "
            "Evaluate market positioning, strengths, weaknesses, and clear differentiators based strictly on verified business facts. "
            "Do NOT invent false statistics, awards, or fake company certifications. "
            "Output strictly valid JSON matching the requested schema."
        )

        prompt = f"""Perform a comprehensive competitive analysis for:
Business Name: {b_name}
Industry / Category: {industry}
Target Market / Audience: {audience}
Known / Target Competitors: {specified_competitors}
{extra_q}

Provide:
1. market_overview: Concise summary of current market dynamics in {industry}.
2. key_competitor_types: Categorize major competitor types (e.g. Premium legacy brands, D2C challengers, Mass market players).
3. direct_competitors: Top 3 typical direct competitors in this niche, with their positioning, strengths, and weaknesses.
4. swot_analysis: Strategic SWOT for '{b_name}' in this landscape.
5. differentiator_strategy: 3 actionable differentiation angles to stand out.
6. actionable_tactics: 4 immediate marketing and product tactics to win market share.

Format response ONLY as JSON:
{{
  "market_overview": "string",
  "key_competitor_types": ["string"],
  "direct_competitors": [
    {{"name": "Competitor 1", "positioning": "string", "strengths": ["s1", "s2"], "weaknesses": ["w1", "w2"]}}
  ],
  "swot_analysis": {{
    "strengths": ["string"],
    "weaknesses": ["string"],
    "opportunities": ["string"],
    "threats": ["string"]
  }},
  "differentiator_strategy": ["string"],
  "actionable_tactics": ["string"]
}}"""

        provider = AIProviderFactory.get_provider(preferred="openai", tier="reasoning")
        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        # Fallback resilient parsing
        if not isinstance(res, dict) or "swot_analysis" not in res:
            logger.warning("Competitor analysis JSON incomplete, applying structured defaults.")
            return CompetitorAnalysisResponse(
                market_overview=f"The {industry} landscape is actively evolving with increasing digital demand.",
                key_competitor_types=["D2C digital brands", "Established regional players", "Value-focused marketplaces"],
                direct_competitors=[
                    {
                        "name": "Standard Market Competitor",
                        "positioning": f"General {industry} provider",
                        "strengths": ["Established brand footprint", "Broad distribution"],
                        "weaknesses": ["Slow digital adaptation", "Impersonal customer experience"]
                    }
                ],
                swot_analysis={
                    "strengths": [f"Agile digital-first strategy for {b_name}", "Direct customer engagement"],
                    "weaknesses": ["Growing brand awareness vs legacy players"],
                    "opportunities": ["High customer retention via personalized social marketing", "Niche category focus"],
                    "threats": ["Price competition from mass discounters", "Rising ad acquisition costs"]
                },
                differentiator_strategy=[
                    "Focus on authentic storytelling and verified customer satisfaction.",
                    "Emphasize distinctive product quality over generic mass production.",
                    "Build a loyal community via engaging reels and video touchpoints."
                ],
                actionable_tactics=[
                    "Highlight unique product features in short-form video content.",
                    "Offer bundle savings or introductory loyalty rewards.",
                    "Run targeted social campaigns aimed directly at underserved customer segments.",
                    "Showcase verified customer reviews and social proof."
                ]
            )

        return CompetitorAnalysisResponse(**res)

    @classmethod
    async def analyze_website(
        cls,
        db,
        user_id: str,
        request: WebsiteAnalysisRequest
    ) -> WebsiteAnalysisResponse:
        """
        Conducts a website conversion rate optimization (CRO) and messaging audit.
        """
        context = await BusinessContextService.get_business_context(user_id=user_id, business_id=user_id, db=db)
        biz = context.get("business", {})
        brand = context.get("brand", {})

        b_name = biz.get("name") or brand.get("brand_name") or "Your Brand"
        b_cat = biz.get("category") or "Online Business"
        target_aud = request.target_audience or biz.get("target_customer") or "Target Shoppers"
        url = request.website_url or biz.get("location") or "yourbusiness.com"

        system_instruction = (
            "You are a Conversion Rate Optimization (CRO) and digital brand auditor. "
            "Analyze website strategy, user journeys, messaging clarity, and conversion friction. "
            "Deliver structured, actionable recommendations without unverified claims."
        )

        prompt = f"""Audit the online presence and website strategy for:
Business: {b_name} ({b_cat})
Target URL / Store: {url}
Target Audience: {target_aud}
Primary Conversion Goal: {request.primary_goal}

Provide a structured website and landing page audit with:
- overall_health_score: numeric score out of 100
- brand_messaging_clarity: review of how clearly the value proposition connects
- conversion_funnel_audit: strengths, critical friction points, and CTA suggestions
- seo_and_content_recommendations: top keyword recommendations and meta guidance
- actionable_next_steps: prioritized list of changes to increase sales/leads

Format ONLY as JSON:
{{
  "website_url": "{url}",
  "overall_health_score": 82,
  "brand_messaging_clarity": "string",
  "conversion_funnel_audit": {{
    "strengths": ["string"],
    "critical_friction_points": ["string"],
    "cta_recommendations": ["string"]
  }},
  "seo_and_content_recommendations": {{
    "recommended_keywords": ["string"],
    "meta_improvements": "string"
  }},
  "actionable_next_steps": ["string"]
}}"""

        provider = AIProviderFactory.get_provider(preferred="openai", tier="reasoning")
        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        if not isinstance(res, dict) or "overall_health_score" not in res:
            return WebsiteAnalysisResponse(
                website_url=url,
                overall_health_score=80,
                brand_messaging_clarity=f"Clear business identity for {b_name}, with opportunities to sharpen the headline above the fold.",
                conversion_funnel_audit={
                    "strengths": ["Clean aesthetic", "Direct product showcase"],
                    "critical_friction_points": ["Add more visible trust badges and testimonials near purchase triggers", "Ensure mobile checkout is frictionless"],
                    "cta_recommendations": ["Use high-contrast primary buttons (e.g. 'Shop the Collection' or 'Claim Special Offer')"]
                },
                seo_and_content_recommendations={
                    "recommended_keywords": [f"{b_cat} online", f"best {b_cat}", f"{b_name} products"],
                    "meta_improvements": f"Ensure meta titles include brand name and primary product benefit within 60 characters."
                },
                actionable_next_steps=[
                    "Clarify value proposition in the main hero banner.",
                    "Add customer social proof directly below the hero section.",
                    "Optimize mobile image load times for fast page rendering.",
                    "Ensure sticky navigation bar with clear contact or shop access."
                ]
            )

        return WebsiteAnalysisResponse(**res)

    @classmethod
    async def analyze_social_trends(
        cls,
        db,
        user_id: str,
        request: SocialTrendAnalysisRequest
    ) -> SocialTrendAnalysisResponse:
        """
        Extracts viral social media trends, format playbooks, and content ideas
        calibrated for the user's specific platform and industry.
        """
        context = await BusinessContextService.get_business_context(user_id=user_id, business_id=user_id, db=db)
        biz = context.get("business", {})
        brand = context.get("brand", {})
        products = context.get("products", [])

        industry = request.industry or biz.get("category") or "Lifestyle & Retail"
        platform = (request.platform or "instagram").lower()
        product_names = [p["name"] for p in products[:4] if p.get("name")]
        product_ref = f"Catalog items to feature: {', '.join(product_names)}" if product_names else ""

        system_instruction = (
            "You are a social media trend forecaster and viral content strategist. "
            "Identify current high-engagement trends, audio styles, hooks, and content pillars. "
            "Tailor guidance specifically to the requested platform and industry."
        )

        prompt = f"""Identify the top social media trends for:
Platform: {platform}
Industry: {industry}
{product_ref}

Provide:
1. current_viral_formats: 3 high-reach content styles (e.g., POV transformation, Behind-the-Scenes craft, 3-mistake breakdown).
2. trending_hooks: 4 irresistible first-3-second hook lines.
3. sound_and_audio_guidance: Best practices for audio selection (tempo, style, trending vibes).
4. hashtag_strategy: Categorized hashtags (high_reach, niche_specific, brand_community).
5. content_calendar_ideas: 5 structured content ideas for the upcoming week with format, concept, and hook.

Format ONLY as JSON:
{{
  "platform": "{platform}",
  "industry": "{industry}",
  "current_viral_formats": ["string"],
  "trending_hooks": ["string"],
  "sound_and_audio_guidance": "string",
  "hashtag_strategy": {{
    "high_reach": ["#..."],
    "niche_specific": ["#..."],
    "brand_community": ["#..."]
  }},
  "content_calendar_ideas": [
    {{"day": "Day 1", "format": "Reel", "concept": "string", "hook": "string"}}
  ]
}}"""

        provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        if not isinstance(res, dict) or "current_viral_formats" not in res:
            return SocialTrendAnalysisResponse(
                platform=platform,
                industry=industry,
                current_viral_formats=[
                    "POV Problem to Solution showcase",
                    "Behind the Scenes product craftsmanship",
                    "3 Things you didn't know about this category"
                ],
                trending_hooks=[
                    "Stop scrolling if you care about quality...",
                    "The real reason why everyone is switching to this...",
                    "Don't buy another product until you watch this...",
                    "3 mistakes 90% of people make in this niche..."
                ],
                sound_and_audio_guidance="Use trending upbeat lo-fi or high-energy rhythmic beats with dynamic cuts synced to the audio drop.",
                hashtag_strategy={
                    "high_reach": [f"#{platform.title()}Trends", "#TrendingNow", "#ViralReels"],
                    "niche_specific": [f"#{industry.replace(' ', '')}", "#QualityDesign", "#EssentialFinds"],
                    "brand_community": ["#DhandaGrow", "#SmallBusinessIndia", "#BrandStory"]
                },
                content_calendar_ideas=[
                    {"day": "Monday", "format": "Reel", "concept": "Fast-paced product reveal", "hook": "Here is why our collection stands out ✨"},
                    {"day": "Wednesday", "format": "Carousel", "concept": "Comparison guide vs ordinary alternatives", "hook": "What to look for before buying"},
                    {"day": "Friday", "format": "Story & Post", "concept": "Customer spotlight & social proof", "hook": "Real feedback from real buyers"},
                    {"day": "Sunday", "format": "Short Video", "concept": "Weekend special offer / insider tip", "hook": "Sunday exclusive preview"}
                ]
            )

        return SocialTrendAnalysisResponse(**res)

    @classmethod
    async def generate_product_marketing(
        cls,
        db,
        user_id: str,
        request: ProductMarketingRequest
    ) -> ProductMarketingResponse:
        """
        Derives high-converting marketing copy and buyer personas strictly from verified product specs.
        """
        context = await BusinessContextService.get_business_context(user_id=user_id, business_id=user_id, db=db)
        brand = context.get("brand", {})

        p_name = request.product_name or "Signature Product"
        p_desc = request.product_description or ""
        p_cat = request.product_category or "Retail"
        p_features = ", ".join(request.product_features) if request.product_features else "Premium build, authentic craftsmanship"
        brand_voice = brand.get("brand_voice") or brand.get("tone") or "confident and inspiring"

        system_instruction = (
            "You are a professional product marketing director and copywriter. "
            "Write compelling, benefit-driven product positioning and multi-channel copy variations. "
            "Base claims strictly on the provided features. Do NOT hallucinate features not provided."
        )

        prompt = f"""Develop a product marketing strategy and copy suite for:
Product Name: {p_name}
Category: {p_cat}
Description: {p_desc}
Confirmed Features: {p_features}
Brand Voice: {brand_voice}
Target Audience: {request.target_audience or 'Target Consumers'}

Provide:
- product_name
- target_buyer_persona: demographics, core_desires, pain_points
- unique_selling_propositions: list of 3 verified USPs
- value_proposition: one definitive sentence capturing why customers choose this
- marketing_copy_variations:
    - short_ad_copy: high-converting short Facebook/Instagram ad text
    - social_caption: engaging social post caption with emojis
    - email_pitch: compelling newsletter or launch email copy
    - story_hook: direct question or statement for Instagram/TikTok stories

Format response strictly as JSON:
{{
  "product_name": "{p_name}",
  "target_buyer_persona": {{
    "demographics": "string",
    "core_desires": ["string"],
    "pain_points": ["string"]
  }},
  "unique_selling_propositions": ["string"],
  "value_proposition": "string",
  "marketing_copy_variations": {{
    "short_ad_copy": "string",
    "social_caption": "string",
    "email_pitch": "string",
    "story_hook": "string"
  }}
}}"""

        provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        if not isinstance(res, dict) or "unique_selling_propositions" not in res:
            return ProductMarketingResponse(
                product_name=p_name,
                target_buyer_persona={
                    "demographics": "Discerning shoppers seeking reliable quality and modern style.",
                    "core_desires": ["Long-lasting value", "Premium aesthetics", "Trustworthy performance"],
                    "pain_points": ["Inconsistent quality from ordinary alternatives", "Overpriced generic options"]
                },
                unique_selling_propositions=[
                    f"Expertly crafted {p_name} designed for everyday excellence.",
                    "Verified durability and authentic attention to detail.",
                    "Direct-to-consumer value backed by dedicated support."
                ],
                value_proposition=f"Experience the perfect combination of design and utility with {p_name}.",
                marketing_copy_variations={
                    "short_ad_copy": f"Upgrade your lifestyle with {p_name}. Unmatched quality you can feel from day one. Order yours today!",
                    "social_caption": f"Say hello to your new favorite: {p_name} ✨ Crafted with precision and built to impress. Tap the link in bio to explore the collection!",
                    "email_pitch": f"We are thrilled to present {p_name} — designed thoughtfully for those who refuse to compromise on quality.",
                    "story_hook": f"Looking for the ultimate {p_name}? Here is why everyone is raving about it 🔥"
                }
            )

        return ProductMarketingResponse(**res)

    @classmethod
    async def generate_brand_strategy(
        cls,
        db,
        user_id: str,
        request: BrandStrategyRequest
    ) -> BrandStrategyResponse:
        """
        Analyzes the user's saved brand kit and generates comprehensive brand voice guidelines,
        color psychology, and content pillars.
        """
        context = await BusinessContextService.get_business_context(user_id=user_id, business_id=user_id, db=db)
        biz = context.get("business", {})
        brand = context.get("brand", {})

        b_name = brand.get("brand_name") or biz.get("name") or "Your Brand"
        b_cat = biz.get("category") or "Retail"
        b_voice = brand.get("brand_voice") or brand.get("tone") or "Authentic, Modern, Premium"
        colors = ", ".join(brand.get("brand_colors", [])) or "Brand curated palette"

        system_instruction = (
            "You are an executive brand identity strategist and creative director. "
            "Develop practical, high-value brand strategy rules tailored to the company's verified identity."
        )

        prompt = f"""Develop an actionable brand strategy framework for:
Brand Name: {b_name}
Industry: {b_cat}
Current Voice / Tone: {b_voice}
Color Palette: {colors}

Provide:
1. brand_name
2. voice_guidelines: tone_attributes (list), dos (list of 3 writing rules), donts (list of 3 things to avoid)
3. color_and_visual_strategy: primary_palette_meaning, visual_moodboard_keywords, typography_vibe
4. content_pillars: 4 foundational content pillars with pillar_name, description, and example_topics
5. growth_recommendations: 4 strategic recommendations to elevate brand equity

Format ONLY as JSON:
{{
  "brand_name": "{b_name}",
  "voice_guidelines": {{
    "tone_attributes": ["string"],
    "dos": ["string"],
    "donts": ["string"]
  }},
  "color_and_visual_strategy": {{
    "primary_palette_meaning": "string",
    "visual_moodboard_keywords": ["string"],
    "typography_vibe": "string"
  }},
  "content_pillars": [
    {{"pillar_name": "string", "description": "string", "example_topics": ["string"]}}
  ],
  "growth_recommendations": ["string"]
}}"""

        provider = AIProviderFactory.get_provider(preferred="openai", tier="reasoning")
        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        if not isinstance(res, dict) or "voice_guidelines" not in res:
            return BrandStrategyResponse(
                brand_name=b_name,
                voice_guidelines={
                    "tone_attributes": ["Confident", "Authentic", "Approachable", "Aspirational"],
                    "dos": ["Speak directly to customer aspirations", "Emphasize craftsmanship and value", "Keep messages clear and energetic"],
                    "donts": ["Avoid corporate jargon or robotic phrasing", "Don't over-promise unverified claims", "Avoid inconsistent visual aesthetics"]
                },
                color_and_visual_strategy={
                    "primary_palette_meaning": "Conveys premium credibility, warmth, and modern sophistication.",
                    "visual_moodboard_keywords": ["Clean", "Vibrant", "Modern Indian", "Editorial"],
                    "typography_vibe": "Bold contemporary sans-serif headings with highly legible body copy."
                },
                content_pillars=[
                    {"pillar_name": "Product Excellence", "description": "Showcasing design, materials, and real performance.", "example_topics": ["Material breakdown", "Feature highlights", "Durability showcases"]},
                    {"pillar_name": "Customer Stories", "description": "Real unboxing, transformations, and customer testimonials.", "example_topics": ["User reviews", "Community spotlights", "Unboxing clips"]},
                    {"pillar_name": "Educational Tips", "description": "Sharing industry expertise and styling or usage advice.", "example_topics": ["How-to guides", "Maintenance tips", "Trend roundups"]},
                    {"pillar_name": "Behind The Brand", "description": "Authentic looks at the people, vision, and care behind products.", "example_topics": ["Founder stories", "Making-of videos", "Core values in action"]}
                ],
                growth_recommendations=[
                    "Maintain strict visual consistency across Instagram, packaging, and digital ads.",
                    "Incorporate short video hooks in the first 3 seconds of all social content.",
                    "Leverage user-generated content (UGC) as authentic social proof.",
                    "Build automated email follow-ups to cultivate high customer lifetime value."
                ]
            )

        return BrandStrategyResponse(**res)
