import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import Response, AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.gemini_service import (
    GeminiService,
    GeminiServiceError,
    GeminiModelUnavailableError,
    GeminiQuotaExceededError,
    generate_with_gemini,
    generateWithGemini,
    sanitize_secrets,
)
from app.schemas.ai import MarketingContentPackage, GeminiGenerateRequest, GeminiGenerateResponse


# =============================================================================
# 1. Secret Sanitization Tests
# =============================================================================

def test_sanitize_secrets_protects_credentials():
    """Verify API keys, tokens, and query parameters are masked."""
    test_str = "Error at https://generativelanguage.googleapis.com/v1beta/interactions?key=AIzaSyA123456789012345678901234567890 with Bearer secret_jwt_token_payload"
    sanitized = sanitize_secrets(test_str)
    assert "AIzaSyA123456789012345678901234567890" not in sanitized
    assert "secret_jwt_token_payload" not in sanitized
    assert "[REDACTED]" in sanitized or "[REDACTED_API_KEY]" in sanitized


# =============================================================================
# 2. Function A — Marketing Content Generation Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_function_a_marketing_content_success():
    """Verify Function A correctly calls generateContent and parses 6-part schema."""
    service = GeminiService(api_key="mock_test_key")

    mock_gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "headline": "Unleash Ultimate Comfort",
                                "bilingual_caption": {
                                    "english": "Experience pure luxury everyday.",
                                    "hindi": "हर दिन अनुभव करें असली आराम।"
                                },
                                "hashtags": ["#Comfort", "#LuxuryLiving", "#Style"],
                                "reel_script": "Scene 1: Close-up on fabric texture.",
                                "video_generation_prompt": "Cinematic vertical 9:16 shot of modern furniture",
                                "image_generation_prompt": "Photorealistic modern living room showcase"
                            })
                        }
                    ]
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_gemini_response)

        result = await service.generate_marketing_content(
            prompt="Luxury Ergonomic Chair",
            model="gemini-2.5-flash"
        )

        assert mock_post.called
        call_args, call_kwargs = mock_post.call_args
        target_url = call_args[0]
        assert "models/gemini-2.5-flash:generateContent" in target_url
        assert call_kwargs["params"]["key"] == "mock_test_key"
        assert call_kwargs["headers"]["x-goog-api-key"] == "mock_test_key"

        assert result["headline"] == "Unleash Ultimate Comfort"
        assert result["bilingual_caption"]["english"] == "Experience pure luxury everyday."
        assert "#Comfort" in result["hashtags"]
        assert "vertical 9:16" in result["video_generation_prompt"]
        assert "living room" in result["image_generation_prompt"]


@pytest.mark.asyncio
async def test_function_a_handles_markdown_fence_cleanly():
    """Verify Function A strips ```json markdown fences returned by models."""
    service = GeminiService(api_key="mock_test_key")

    raw_markdown = "```json\n" + json.dumps({
        "headline": "Winter Collection Launch",
        "bilingual_caption": {"english": "Warm up this winter.", "hindi": "सर्दियों का नया अंदाज़।"},
        "hashtags": ["#WinterFashion"],
        "reel_script": "Scene 1: Snow falling on jacket.",
        "video_generation_prompt": "Vertical 9:16 video of winter outerwear",
        "image_generation_prompt": "Photorealistic winter jacket model"
    }) + "\n```"

    mock_resp = {
        "candidates": [{"content": {"parts": [{"text": raw_markdown}]}}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_resp)
        result = await service.generate_marketing_content(prompt="Winter jacket")
        assert result["headline"] == "Winter Collection Launch"
        assert "#WinterFashion" in result["hashtags"]


@pytest.mark.asyncio
async def test_function_a_reports_deprecated_model_404():
    """Verify Function A surfaces clear 404 error without silent replacement."""
    service = GeminiService(api_key="mock_test_key")

    error_body = {
        "error": {
            "code": 404,
            "message": "This model models/gemini-2.5-flash is no longer available to new users.",
            "status": "NOT_FOUND"
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(404, json=error_body)

        with pytest.raises(GeminiModelUnavailableError) as exc_info:
            await service.generate_marketing_content(prompt="Test", model="gemini-2.5-flash")

        assert exc_info.value.status_code == 404
        assert "gemini-2.5-flash" in exc_info.value.message
        assert "unavailable or not accessible" in exc_info.value.message


# =============================================================================
# 3. Function B — Promotional Video Generation Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_function_b_promotional_video_success():
    """Verify Function B calls /interactions with gemini-omni-1.1-flash and extracts video."""
    service = GeminiService(api_key="mock_test_key")

    mock_interaction_resp = {
        "id": "interaction_video_12345",
        "status": "completed",
        "model": "gemini-omni-1.1-flash",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "video",
                        "url": "https://storage.googleapis.com/sample_videos/promo_9_16.mp4"
                    }
                ]
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_interaction_resp)

        result = await service.generate_promotional_video(
            prompt="Vertical 9:16 video of artisanal bakery",
            model="gemini-omni-1.1-flash"
        )

        assert mock_post.called
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0].endswith("/interactions")
        sent_json = call_kwargs["json"]
        assert sent_json["model"] == "gemini-omni-1.1-flash"
        assert "vertical 9:16" in sent_json["input"].lower()

        assert result["status"] == "completed"
        assert result["video_url"] == "https://storage.googleapis.com/sample_videos/promo_9_16.mp4"
        assert result["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_function_b_async_polling_workflow():
    """Verify Function B polls GET /interactions/{id} when initial status is in_progress."""
    service = GeminiService(api_key="mock_test_key")

    initial_resp = {
        "id": "v1_async_job_999",
        "status": "in_progress",
        "model": "gemini-omni-1.1-flash"
    }

    completed_resp = {
        "id": "v1_async_job_999",
        "status": "completed",
        "model": "gemini-omni-1.1-flash",
        "video_url": "https://storage.googleapis.com/sample_videos/rendered_reel.mp4"
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:

        mock_post.return_value = Response(200, json=initial_resp)
        mock_get.return_value = Response(200, json=completed_resp)

        result = await service.generate_promotional_video(
            prompt="Reel of cafe latte art",
            model="gemini-omni-1.1-flash",
            poll=True,
            max_wait_seconds=5,
            poll_interval=1
        )

        assert mock_post.called
        assert mock_get.called
        poll_call_args = mock_get.call_args[0]
        assert "interactions/v1_async_job_999" in poll_call_args[0]
        assert result["status"] == "completed"
        assert result["video_url"] == "https://storage.googleapis.com/sample_videos/rendered_reel.mp4"


@pytest.mark.asyncio
async def test_function_b_reports_rate_limit_429():
    """Verify Function B surfaces HTTP 429 quota limits clearly."""
    service = GeminiService(api_key="mock_test_key")

    error_body = {
        "error": {
            "message": "Rate limit exceeded for model gemini-omni-1.1-flash (limit: 0 input tokens per minute on Free Tier).",
            "code": "too_many_requests"
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(429, json=error_body)

        with pytest.raises(GeminiQuotaExceededError) as exc_info:
            await service.generate_promotional_video(
                prompt="Reel prompt",
                model="gemini-omni-1.1-flash"
            )

        assert exc_info.value.status_code == 429
        assert "gemini-omni-1.1-flash" in exc_info.value.message
        assert "Quota or rate limit exceeded" in exc_info.value.message


# =============================================================================
# 4. Function C — Advertisement Image Generation Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_function_c_advertisement_image_success():
    """Verify Function C calls /interactions with gemini-nano-banana-2.1 and returns image."""
    service = GeminiService(api_key="mock_test_key")

    mock_resp = {
        "id": "interaction_img_777",
        "status": "completed",
        "model": "gemini-nano-banana-2.1",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "image",
                        "url": "https://storage.googleapis.com/images/instagram_ad.jpg"
                    }
                ]
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json=mock_resp)

        result = await service.generate_advertisement_image(
            prompt="Premium Organic Green Tea Advertisement",
            model="gemini-nano-banana-2.1"
        )

        assert mock_post.called
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0].endswith("/interactions")
        assert call_kwargs["json"]["model"] == "gemini-nano-banana-2.1"
        assert result["image_url"] == "https://storage.googleapis.com/images/instagram_ad.jpg"


@pytest.mark.asyncio
async def test_function_c_reports_rate_limit_429():
    """Verify Function C surfaces HTTP 429 without silent substitution."""
    service = GeminiService(api_key="mock_test_key")

    error_body = {
        "error": {
            "message": "Rate limit exceeded for model gemini-nano-banana-2.1 (limit: 0 requests per day on Free Tier).",
            "code": "too_many_requests"
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(429, json=error_body)

        with pytest.raises(GeminiQuotaExceededError) as exc_info:
            await service.generate_advertisement_image(
                prompt="Perfume Ad",
                model="gemini-nano-banana-2.1"
            )

        assert exc_info.value.status_code == 429
        assert "gemini-nano-banana-2.1" in exc_info.value.message


# =============================================================================
# 5. Automatic Task Switching Tests
# =============================================================================

@pytest.mark.asyncio
async def test_automatic_switching_routing():
    """Verify generate_with_gemini correctly selects the right function and model for each task."""

    with patch.object(GeminiService, "generate_marketing_content", new_callable=AsyncMock) as mock_a, \
         patch.object(GeminiService, "generate_promotional_video", new_callable=AsyncMock) as mock_b, \
         patch.object(GeminiService, "generate_advertisement_image", new_callable=AsyncMock) as mock_c:

        mock_a.return_value = {"headline": "Test Headline", "bilingual_caption": "Capt", "hashtags": [], "reel_script": "", "video_generation_prompt": "", "image_generation_prompt": ""}
        mock_b.return_value = {"status": "completed", "video_url": "test.mp4"}
        mock_c.return_value = {"status": "completed", "image_url": "test.jpg"}

        # Task 1: marketing_content
        r1 = await generate_with_gemini({
            "task": "marketing_content",
            "prompt": "Handmade soap promo"
        })
        assert r1["success"] is True
        assert r1["task"] == "marketing_content"
        assert mock_a.called
        assert not mock_b.called
        assert not mock_c.called

        # Task 2: video_generation
        mock_a.reset_mock()
        r2 = await generate_with_gemini({
            "task": "video_generation",
            "prompt": "Handmade soap video"
        })
        assert r2["success"] is True
        assert r2["task"] == "video_generation"
        assert mock_b.called
        assert not mock_a.called

        # Task 3: image_generation
        mock_b.reset_mock()
        r3 = await generate_with_gemini({
            "task": "image_generation",
            "prompt": "Handmade soap photo"
        })
        assert r3["success"] is True
        assert r3["task"] == "image_generation"
        assert mock_c.called
        assert not mock_b.called

        # Also verify camelCase alias
        mock_c.reset_mock()
        r4 = await generateWithGemini(
            task="image_generation",
            prompt="Handmade soap photo"
        )
        assert r4["success"] is True
        assert mock_c.called


@pytest.mark.asyncio
async def test_automatic_switching_invalid_task():
    """Verify invalid task raises ValueError."""
    with pytest.raises(ValueError) as exc:
        await generate_with_gemini({"task": "unknown_quantum_task", "prompt": "Hi"})
    assert "Unsupported task" in str(exc.value)


# =============================================================================
# 6. REST API Endpoint Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_api_generate_endpoint():
    """Verify POST /api/v1/ai/generate route handles tasks and returns standard response."""
    with patch("app.api.endpoints.ai.generate_with_gemini", new_callable=AsyncMock) as mock_dispatcher:
        mock_dispatcher.return_value = {
            "success": True,
            "task": "marketing_content",
            "model": "gemini-2.5-flash",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            "data": {
                "headline": "Super Promo",
                "bilingual_caption": "Dual",
                "hashtags": ["#Tag"],
                "reel_script": "Script",
                "video_generation_prompt": "Prompt V",
                "image_generation_prompt": "Prompt I"
            },
            "error": None
        }

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "task": "marketing_content",
                "prompt": "Premium Leather Wallet"
            }
            resp = await ac.post("/api/v1/ai/generate", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["task"] == "marketing_content"
            assert data["data"]["headline"] == "Super Promo"
