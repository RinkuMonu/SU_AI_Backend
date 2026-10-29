import pytest
import json
from unittest.mock import AsyncMock, patch
from httpx import Response, AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.gemini_service import GeminiService


@pytest.mark.asyncio
async def test_generate_content_native_gemini_format():
    """
    Verify POST /api/v1/ai/generateContent accepts the exact native Google Gemini cURL
    payload with {"contents": [{"parts": [{"text": "..."}]}]} and returns structured output.
    """
    mock_service_response = {
        "text": "AI analyzes data patterns to make predictions and decisions autonomously.",
        "model": "gemini-3.5-flash",
        "provider": "gemini",
        "usage": {
            "promptTokenCount": 9,
            "candidatesTokenCount": 11,
            "totalTokenCount": 20
        }
    }

    with patch.object(GeminiService, "generate_text_content", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_service_response

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": "Explain how AI works in a few words"
                            }
                        ]
                    }
                ]
            }
            resp = await ac.post("/api/v1/ai/generateContent", json=payload)

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "AI analyzes data patterns" in data["text"]
            assert data["candidates"][0]["content"]["parts"][0]["text"] == data["text"]
            assert data["model"] == "gemini-3.5-flash"
            assert data["provider"] == "gemini"
            assert mock_gen.called
            call_kwargs = mock_gen.call_args.kwargs
            assert "Explain how AI works in a few words" in call_kwargs["prompt"]


@pytest.mark.asyncio
async def test_generate_content_simple_prompt_format():
    """Verify endpoint also accepts standard prompt format."""
    mock_service_response = {
        "text": "Smart systems learning from examples.",
        "model": "gemini-3.5-flash",
        "provider": "gemini",
        "usage": {}
    }

    with patch.object(GeminiService, "generate_text_content", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_service_response

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ai/generateContent",
                json={"prompt": "Explain AI in 5 words", "model": "gemini-3.5-flash"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "Smart systems" in data["text"]


@pytest.mark.asyncio
async def test_generate_content_missing_prompt_400():
    """Verify endpoint returns 400 when neither contents nor prompt is supplied."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/ai/generateContent", json={})
        assert resp.status_code == 400
        assert "Missing required 'contents' or 'prompt'" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_gemini_service_text_generation_trained_persona():
    """Verify GeminiService generates text with the trained DhandaGrow system persona."""
    service = GeminiService(api_key="mock_test_key")

    mock_gemini_response = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Learns patterns from data."}]
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 15}
    }

    mock_post_resp = Response(200, json=mock_gemini_response)
    with patch.object(service, "_post_with_key_failover", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_post_resp

        res = await service.generate_text_content(
            prompt="Explain how AI works in a few words",
            model="gemini-3.5-flash"
        )

        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        target_url = call_kwargs["endpoint"]
        assert "models/gemini-3.5-flash:generateContent" in target_url

        payload = call_kwargs["payload"]
        # Verify trained system instruction was included
        system_inst = payload["systemInstruction"]["parts"][0]["text"]
        assert "DhandaGrow AI" in system_inst
        assert "SevenUnique" in system_inst
        assert res["text"] == "Learns patterns from data."
