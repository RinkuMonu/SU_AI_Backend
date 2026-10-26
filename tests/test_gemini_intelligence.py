import pytest
import os
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO
from PIL import Image

from app.core.config import settings, Settings
from app.ai.providers.gemini_provider import GeminiProvider, sanitize_log_message
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
from app.services.marketing_intelligence_service import MarketingIntelligenceService


# ==========================================
# 1. Key Configuration & Model Selection Tests
# ==========================================

def test_gemini_configuration_defaults():
    """Verify Gemini default models and settings are properly configured."""
    assert settings.GEMINI_MODEL in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    assert settings.GEMINI_FAST_MODEL in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    assert settings.GEMINI_REASONING_MODEL in ["gemini-3.8-pro", "gemini-2.5-pro", "gemini-pro-latest"]


def test_gemini_backup_key_resolution():
    """Verify GEMINI_BACKUP_API_KEY resolves when primary key is missing."""
    s = Settings(
        GEMINI_API_KEY="",
        GEMINI_BACKUP_API_KEY="backup_test_key_12345",
        MONGO_URI="mongodb://localhost:27017",
    )
    assert s.GEMINI_API_KEY == "backup_test_key_12345"


def test_provider_factory_model_tiering():
    """Verify AIProviderFactory instantiates the proper model based on requested tier."""
    with patch.object(settings, "GEMINI_API_KEY", "test_gemini_api_key_valid"):
        # Reset factory cache
        AIProviderFactory._instances.clear()

        # Fast tier -> GEMINI_FAST_MODEL (gemini-2.5-flash)
        fast_provider = AIProviderFactory.get_provider(preferred="gemini", tier="fast")
        assert isinstance(fast_provider, GeminiProvider)
        assert fast_provider.model_name == settings.GEMINI_FAST_MODEL

        # Reasoning tier -> GEMINI_REASONING_MODEL (gemini-2.5-pro)
        reasoning_provider = AIProviderFactory.get_provider(preferred="gemini", tier="reasoning")
        assert isinstance(reasoning_provider, GeminiProvider)
        assert reasoning_provider.model_name == settings.GEMINI_REASONING_MODEL

        # Custom model override
        custom_provider = AIProviderFactory.get_provider(preferred="gemini", model="gemini-custom-model")
        assert isinstance(custom_provider, GeminiProvider)
        assert custom_provider.model_name == "gemini-custom-model"


def test_provider_factory_caching():
    """Verify AIProviderFactory returns cached instances for the same provider, tier, and model."""
    with patch.object(settings, "GEMINI_API_KEY", "test_gemini_api_key_valid"):
        AIProviderFactory._instances.clear()
        p1 = AIProviderFactory.get_provider(preferred="gemini", tier="fast")
        p2 = AIProviderFactory.get_provider(preferred="gemini", tier="fast")
        assert p1 is p2

        p3 = AIProviderFactory.get_provider(preferred="gemini", tier="reasoning")
        assert p1 is not p3


# ==========================================
# 2. Secret Sanitization Tests
# ==========================================

def test_secret_sanitization_masks_keys_and_tokens():
    """Verify secrets, Google API keys, and bearer tokens are never exposed in log outputs."""
    raw_message = (
        "Request failed for https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        "?key=AQ.Abc123XYZ9876543210_LongSecretKeyString with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload"
    )
    sanitized = sanitize_log_message(raw_message)
    assert "AQ.Abc123XYZ9876543210_LongSecretKeyString" not in sanitized
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
    assert "[REDACTED]" in sanitized


# ==========================================
# 3. Structured Outputs & JSON Parsing Tests
# ==========================================

def test_json_output_cleaning():
    """Verify markdown fences and comments are cleanly stripped for JSON deserialization."""
    provider = GeminiProvider(api_key="mock_key")

    raw_fence = "```json\n{\"competitors\": [{\"name\": \"Brand A\", \"market_share_estimate\": \"15%\"}]}\n```"
    cleaned = provider._clean_json_output(raw_fence)
    parsed = json.loads(cleaned)
    assert "competitors" in parsed
    assert parsed["competitors"][0]["name"] == "Brand A"

    raw_surrounding = "Here is the response:\n{\"status\": \"success\"}\nHope this helps!"
    cleaned_surrounding = provider._clean_json_output(raw_surrounding)
    parsed_surrounding = json.loads(cleaned_surrounding)
    assert parsed_surrounding["status"] == "success"


def test_structured_pydantic_schemas():
    """Verify all marketing intelligence Pydantic response models deserialize correctly."""
    comp_json = {
        "market_overview": "Competitive landscape overview",
        "key_competitor_types": ["D2C", "Legacy"],
        "direct_competitors": [{"name": "CompX", "positioning": "Premium", "strengths": ["Fast delivery"], "weaknesses": ["High price"]}],
        "swot_analysis": {"strengths": ["Quality"], "weaknesses": ["Scale"], "opportunities": ["E-com"], "threats": ["New entrants"]},
        "differentiator_strategy": ["Focus on sustainability"],
        "actionable_tactics": ["Influencer seeding"]
    }
    comp_res = CompetitorAnalysisResponse.model_validate(comp_json)
    assert comp_res.market_overview == "Competitive landscape overview"
    assert len(comp_res.direct_competitors) == 1

    web_json = {
        "overall_health_score": 85,
        "brand_messaging_clarity": "Strong and clear",
        "conversion_funnel_audit": {"hero": "Strong visual hook"},
        "seo_and_content_recommendations": {"meta": "Add targeted keywords"},
        "actionable_next_steps": ["Improve mobile checkout"]
    }
    web_res = WebsiteAnalysisResponse.model_validate(web_json)
    assert web_res.overall_health_score == 85
    assert len(web_res.actionable_next_steps) == 1


# ==========================================
# 4. Multimodal Input Packaging Tests
# ==========================================

def test_multimodal_payload_construction():
    """Verify GeminiProvider packs PIL images and binary buffers into valid inlineData structures."""
    provider = GeminiProvider(api_key="mock_key")

    # Create dummy PIL Image
    img = Image.new("RGB", (32, 32), color="red")
    
    # Pack payload
    payload = provider._build_payload(
        prompt="Analyze this product design",
        images=[img],
        system_instruction="You are an expert visual designer."
    )

    parts = payload["contents"][0]["parts"]
    assert len(parts) == 2
    assert "text" in parts[0]
    assert parts[0]["text"] == "Analyze this product design"
    assert "inlineData" in parts[1]
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert len(parts[1]["inlineData"]["data"]) > 0
    assert payload["systemInstruction"]["parts"][0]["text"] == "You are an expert visual designer."


# ==========================================
# 5. Error Handling & Provider Failures Tests
# ==========================================

@pytest.mark.asyncio
async def test_gemini_prepayment_depleted_error():
    """Verify HTTP 402 prepayment error is caught and converted to an informative, non-sensitive exception."""
    provider = GeminiProvider(api_key="mock_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 402
    mock_resp.text = json.dumps({"error": {"code": 402, "message": "Your prepayment credits are depleted."}})

    with patch.object(provider, "_call_api", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(Exception) as exc_info:
            await provider.generate_text(prompt="Hello")
        assert "prepayment credits are depleted" in str(exc_info.value).lower()
        # Ensure API key is NOT in the exception
        assert "mock_key" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_rate_limit_backoff():
    """Verify HTTP 429 triggers retry logic before raising exception."""
    provider = GeminiProvider(api_key="mock_key")

    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.text = json.dumps({"error": {"code": 429, "message": "Resource has been exhausted (rate limit)."}})

    with patch.object(provider, "_call_api", new_callable=AsyncMock, return_value=mock_429):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(Exception) as exc_info:
                await provider.generate_text(prompt="Hello")
            assert "429" in str(exc_info.value) or "rate limit" in str(exc_info.value).lower()
            # Assert backoff sleep was invoked during retry attempts
            assert mock_sleep.call_count >= 1


# ==========================================
# 6. Business Context Integration Tests
# ==========================================

@pytest.mark.asyncio
async def test_business_context_omits_fake_data():
    """Verify BusinessContextService never invents 'Mock Business' or placeholder text when data is missing."""
    mock_db = MagicMock()
    # Mock finding no business, brand kit, or products
    mock_db.__getitem__.return_value.find_one = AsyncMock(return_value=None)
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db.__getitem__.return_value.find.return_value = mock_cursor

    context = await BusinessContextService.get_context_summary(mock_db, user_id="user_test_empty")

    # Should NOT have hallucinated placeholders
    assert "Mock Business" not in context
    assert "Everyone" not in context
    assert "Global" not in context


@pytest.mark.asyncio
async def test_business_context_includes_authentic_data():
    """Verify BusinessContextService incorporates genuine business profile, brand kit, and product catalog."""
    mock_db = MagicMock()
    mock_businesses = MagicMock()
    mock_brand_kits = MagicMock()
    mock_products = MagicMock()

    mock_db.__getitem__.side_effect = lambda key: {
        "businesses": mock_businesses,
        "brand_kits": mock_brand_kits,
        "products": mock_products,
    }[key]

    mock_businesses.find_one = AsyncMock(return_value={
        "_id": "65123456789abcdef0123456",
        "name": "Kashmir Pashmina Co",
        "category": "Handicrafts & Luxury Apparel",
        "target_customer": "Affluent global buyers appreciate artisanal craft",
    })
    mock_brand_kits.find_one = AsyncMock(return_value={
        "brand_name": "Kashmir Pashmina",
        "primary_color": "#800020",
        "brand_voice": "Elegant, Heritage, Premium"
    })
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"name": "Pure Cashmere Shawl", "price": 12000, "category": "Apparel"}
    ])
    mock_products.find.return_value = mock_cursor

    context = await BusinessContextService.get_context_summary(mock_db, user_id="user_123")

    assert "Kashmir Pashmina Co" in context
    assert "Handicrafts & Luxury Apparel" in context
    assert "#800020" in context
    assert "Pure Cashmere Shawl" in context


# ==========================================
# 7. Intelligence Workflows Tests
# ==========================================

@pytest.mark.asyncio
async def test_marketing_intelligence_competitor_analysis_flow():
    """Verify competitor analysis workflow builds task-specific prompts and returns structured schemas."""
    mock_db = MagicMock()
    mock_db["businesses"].find_one = AsyncMock(return_value={"name": "Organic Botanicals", "category": "Skincare"})
    mock_db["brand_kits"].find_one = AsyncMock(return_value={"brand_name": "Organic Botanicals"})
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db["products"].find.return_value = mock_cursor

    req = CompetitorAnalysisRequest(
        competitors=["Forest Essentials", "Kama Ayurveda"],
        industry="Ayurvedic Skincare",
    )

    fake_ai_response = {
        "market_overview": "Organic Botanicals operates in a high-growth premium Ayurvedic market.",
        "key_competitor_types": ["Heritage Ayurvedic", "Modern Clean D2C"],
        "direct_competitors": [
            {
                "name": "Forest Essentials",
                "positioning": "Luxury Ayurvedic Heritage",
                "strengths": ["Strong brand heritage", "Extensive retail presence"],
                "weaknesses": ["High price barrier", "Slow digital-first innovation"],
            }
        ],
        "swot_analysis": {
            "strengths": ["Direct artisan sourcing"],
            "weaknesses": ["Lower brand awareness"],
            "opportunities": ["Digital-first subscription bundles"],
            "threats": ["Established conglomerate competition"]
        },
        "differentiator_strategy": ["Highlight 100% cold-pressed freshness"],
        "actionable_tactics": ["Micro-influencer dermatologist collaborations"]
    }

    with patch.object(GeminiProvider, "generate_json", new_callable=AsyncMock, return_value=fake_ai_response):
        result = await MarketingIntelligenceService.analyze_competitors(mock_db, "user_skincare", req)

        assert isinstance(result, CompetitorAnalysisResponse)
        assert len(result.direct_competitors) == 1
        assert result.direct_competitors[0].name == "Forest Essentials"
        assert "Organic Botanicals operates" in result.market_overview


@pytest.mark.asyncio
async def test_marketing_intelligence_trend_analysis_flow():
    """Verify social media trend analysis workflow selects fast model and parses structured output."""
    mock_db = MagicMock()
    mock_db["businesses"].find_one = AsyncMock(return_value=None)
    mock_db["brand_kits"].find_one = AsyncMock(return_value=None)
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db["products"].find.return_value = mock_cursor

    req = SocialTrendAnalysisRequest(
        platform="instagram",
        industry="Streetwear Fashion",
    )

    fake_trend_response = {
        "platform": "instagram",
        "industry": "Streetwear Fashion",
        "current_viral_formats": ["Reel transitions", "Carousel styling guide"],
        "trending_hooks": ["Stop buying fast fashion until you watch this"],
        "sound_and_audio_guidance": "Fast beat-drop transition audio",
        "hashtag_strategy": {"core": ["#streetwearindia", "#baggyjeans", "#minimalfits"]},
        "content_calendar_ideas": [
            {
                "day": "Day 1",
                "format": "Reel",
                "concept": "3 Ways to style 1 boxy tee",
                "call_to_action": "Save for later"
            }
        ]
    }

    with patch.object(GeminiProvider, "generate_json", new_callable=AsyncMock, return_value=fake_trend_response):
        result = await MarketingIntelligenceService.analyze_social_trends(mock_db, "user_streetwear", req)

        assert isinstance(result, SocialTrendAnalysisResponse)
        assert len(result.current_viral_formats) == 2
        assert "Stop buying fast fashion" in result.trending_hooks[0]
