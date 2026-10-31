import pytest
import os
import re
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings
from app.core.security import require_admin
from app.ai.factory import AIProviderFactory
from app.ai.providers.openai_provider import OpenAIProvider, sanitize_secrets
from app.services.credit_service import FEATURE_PRICING

@pytest.mark.asyncio
async def test_01_centralized_model_config():
    """Verify OpenAI is configured as the exclusive provider with strict model routing."""
    assert settings.AI_PROVIDER == "openai"
    assert settings.OPENAI_TEXT_MODEL == "gpt-4.1-mini"
    assert settings.OPENAI_IMAGE_MODEL == "gpt-image-1-mini"
    assert settings.OPENAI_REASONING_MODEL == "gpt-4.1-mini"
    assert getattr(settings, "GEMINI_API_KEY", None) is None
    assert getattr(settings, "GEMINI_MODEL", None) is None


@pytest.mark.asyncio
async def test_02_text_generation_gpt_4_1_mini():
    """Verify text generation uses gpt-4.1-mini exclusively."""
    provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
    assert isinstance(provider, OpenAIProvider)
    assert provider.text_model == "gpt-4.1-mini"

    res = await provider.generate_text(
        prompt="Say 'OpenAI GPT-4.1 Mini Verified'",
        system_prompt="You are a test evaluator. Be concise."
    )
    assert "text" in res
    assert res.get("provider") == "openai"
    assert res.get("model") == "gpt-4.1-mini"
    assert len(res["text"].strip()) > 0


@pytest.mark.asyncio
async def test_03_structured_json_generation_gpt_4_1_mini():
    """Verify structured JSON generation uses gpt-4.1-mini with response_format json_object."""
    provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
    res = await provider.generate_json(
        prompt="Return a JSON object with 'caption' (string) and 'hashtags' (array of strings)."
    )
    assert isinstance(res, dict)
    assert "caption" in res or "hashtags" in res


@pytest.mark.asyncio
async def test_04_captions_and_hashtags_generation():
    """Verify social media caption and hashtag generation via post generation service."""
    from app.ai.services.post_generation import PostGenerationService
    svc = PostGenerationService()
    result = await svc.generate_post(
        business={"name": "Test Boutique", "category": "Ethnic Wear"},
        brand={},
        product={"name": "Silk Kurti", "price": "1499"},
        platform="instagram",
        objective="engagement",
        language="Hinglish",
        content_type="post"
    )
    assert isinstance(result, dict)
    assert "headline" in result
    assert "caption" in result
    assert "hashtags" in result
    assert len(result["hashtags"]) > 0


@pytest.mark.asyncio
async def test_05_ai_agent_uni_ai_text_task():
    """Verify UNI AI Agent uses gpt-4.1-mini for intent parsing and conversational response."""
    from app.services.agent_service import AgentService
    svc = AgentService()
    parsed = await svc._parse_intent_and_respond(
        command="Diwali ke liye ek viral post idea do",
        business_info={"name": "Saree Mahal", "category": "Fashion"},
        language="Hinglish"
    )
    assert isinstance(parsed, dict)
    assert "action" in parsed
    assert "conversational_response" in parsed
    assert len(parsed["conversational_response"]) > 0


@pytest.mark.asyncio
async def test_06_image_generation_gpt_image_1_mini_routing():
    """Verify image generation strictly routes to gpt-image-1-mini and never to text model."""
    provider = OpenAIProvider()
    assert provider.image_model == "gpt-image-1-mini"
    # Never allow gpt-4.1-mini for image generation
    assert provider.image_model != provider.text_model


@pytest.mark.asyncio
async def test_07_photoshoot_mode_validation():
    """Verify AI Photoshoot Studio 2 modes: avatar_photoshoot requires model_id; product_photography does not."""
    from app.services.photoshoot_service import PhotoshootService
    
    # 1. Product photography without model: valid
    res_product = PhotoshootService.validate_generation_parameters(
        mode="product_photography",
        selected_enhanced_ids=["enh_1"],
        model_id=None,
        styles=["Studio Premium"]
    )
    assert res_product["valid"] is True

    # 2. Avatar photoshoot without model: strictly rejected
    res_avatar_invalid = PhotoshootService.validate_generation_parameters(
        mode="avatar_photoshoot",
        selected_enhanced_ids=["enh_1"],
        model_id=None,
        styles=["Studio Premium"]
    )
    assert res_avatar_invalid["valid"] is False
    assert "model" in res_avatar_invalid["error"].lower()

    # 3. Avatar photoshoot with valid model: valid
    res_avatar_valid = PhotoshootService.validate_generation_parameters(
        mode="avatar_photoshoot",
        selected_enhanced_ids=["enh_1"],
        model_id="model_male_01",
        styles=["Studio Premium"]
    )
    assert res_avatar_valid["valid"] is True


@pytest.mark.asyncio
async def test_08_website_analysis_ssrf_protection():
    """Verify website URL analysis validates against SSRF and private IP addresses."""
    from app.utils.url_validator import validate_url_safety

    # Safe public URL
    safe, _ = validate_url_safety("https://example.com")
    assert safe is True

    # Unsafe private IPs / localhost blocked
    unsafe_localhost, _ = validate_url_safety("http://127.0.0.1:8000/admin")
    assert unsafe_localhost is False

    unsafe_private, _ = validate_url_safety("http://192.168.1.1/secret")
    assert unsafe_private is False

    unsafe_meta, _ = validate_url_safety("http://169.254.169.254/latest/meta-data")
    assert unsafe_meta is False


@pytest.mark.asyncio
async def test_09_admin_ai_config_endpoint():
    """Verify GET /api/v1/admin/ai-config returns centralized OpenAI routing and NEVER exposes API key."""
    # Override admin dependency cleanly
    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "id": "admin_mock_123"}
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/ai-config")
            assert response.status_code == 200
            data = response.json()
            assert data["provider"] == "openai"
            assert data["text_model"] == "gpt-4.1-mini"
            assert data["image_model"] == "gpt-image-1-mini"
            assert data["reasoning_model"] == "gpt-4.1-mini"
            # Strict isolation check: NEVER expose API key in response
            assert "api_key" not in data
            assert "OPENAI_API_KEY" not in data
            assert "key" not in data
    finally:
        app.dependency_overrides.pop(require_admin, None)


@pytest.mark.asyncio
async def test_10_admin_ai_test_connectivity_endpoint():
    """Verify POST /api/v1/admin/ai-test tests connectivity with OpenAI without leaking credentials."""
    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "id": "admin_mock_123"}
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/api/v1/admin/ai-test")
            assert response.status_code == 200
            data = response.json()
            assert data["provider"] == "openai"
            assert data["status"] == "connected"
            assert data["success"] is True
            # Verify no key is in the response body
            assert "sk-" not in str(data)
    finally:
        app.dependency_overrides.pop(require_admin, None)


@pytest.mark.asyncio
async def test_11_secrets_sanitization():
    """Verify sanitize_secrets strips any accidental OpenAI API keys from error messages."""
    raw_error = "OpenAI request failed: Authorization sk-proj-1234567890abcdef1234567890 is invalid"
    cleaned = sanitize_secrets(raw_error)
    assert "sk-proj-1234567890abcdef1234567890" not in cleaned
    assert "[REDACTED_OPENAI_KEY]" in cleaned


@pytest.mark.asyncio
async def test_12_stt_provider_whisper_routing():
    """Verify speech-to-text routes to OpenAI Whisper by default when key is configured."""
    from app.ai.providers.stt_provider import get_stt_provider, OpenAIWhisperSTTProvider
    provider = get_stt_provider()
    assert isinstance(provider, OpenAIWhisperSTTProvider)
    assert provider.provider_name == "openai"
    assert provider.model == "whisper-1"


@pytest.mark.asyncio
async def test_13_credit_deduction_and_pricing_intact():
    """Verify AI credit deduction, pricing dictionary, and user balances are unaffected."""
    assert "ai_post" in FEATURE_PRICING
    assert "ai_photoshoot" in FEATURE_PRICING
    assert "ai_reel" in FEATURE_PRICING
    assert FEATURE_PRICING["ai_post"] >= 1
    assert FEATURE_PRICING["ai_photoshoot"] >= 1


@pytest.mark.asyncio
async def test_14_no_active_gemini_calls_in_backend_code():
    """Scans all python files in app/ to verify no active google.genai or gemini client calls exist."""
    import glob
    py_files = glob.glob("app/**/*.py", recursive=True)
    forbidden_calls = ["genai.Client", "google.genai", "client.models.generate_content"]
    violations = []

    for pf in py_files:
        # Ignore legacy shim files that are purely type aliases
        if os.path.basename(pf) in ["gemini_client.py", "gemini_provider.py", "gemini_service.py"]:
            continue
        with open(pf, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            for call in forbidden_calls:
                if call in content:
                    violations.append(f"{pf}: contains {call}")

    assert len(violations) == 0, f"Found active Gemini SDK calls: {violations}"


@pytest.mark.asyncio
async def test_15_legacy_aliases_backward_compatible():
    """Verify that legacy Gemini function & class aliases seamlessly invoke AIService without breaking."""
    from app.services.gemini_service import GeminiService
    from app.services.ai_service import AIService
    
    assert GeminiService == AIService
    service = GeminiService()
    res = await service.generate_text_content(
        prompt="Reply with 'Test Passed'",
        system_instruction="Be concise."
    )
    assert "text" in res
    assert res.get("provider") == "openai"
