import json
import logging
import asyncio
from typing import Dict, Any, List
import httpx

from app.ai.base import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    """
    Google Gemini AI provider using asynchronous REST API with automatic multi-model fallback.
    """

    def __init__(self, api_key: str = None, model: str = None):
        primary_key = api_key or settings.GEMINI_API_KEY
        backup_key = getattr(settings, "GEMINI_BACKUP_API_KEY", None)

        self.api_keys_to_try = [k for k in [primary_key, backup_key] if k]
        if not self.api_keys_to_try:
            raise ValueError("GEMINI_API_KEY is missing from configuration.")

        configured_model = model or settings.GEMINI_MODEL or "gemini-flash-lite-latest"
        
        # Priority list of models with proven Gemini API availability
        fallback_models = [
            configured_model,
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
        ]
        seen = set()
        self.models_to_try = []
        for m in fallback_models:
            if m not in seen:
                seen.add(m)
                self.models_to_try.append(m)

    async def generate_text(self, prompt: str, system_prompt: str = None, **kwargs) -> Dict[str, Any]:
        """
        Generates text using Google Gemini REST API.
        Supports system instructions, temperature, max tokens, and JSON mode.
        Automatically fails over across models and configured API keys upon 402, 429, or 404.
        """
        is_json = False
        if "response_format" in kwargs and kwargs["response_format"].get("type") == "json_object":
            is_json = True

        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 8192)

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        if is_json:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        last_error = None

        for current_key in self.api_keys_to_try:
            for current_model in self.models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent"
                params = {"key": current_key}

                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        response = await client.post(url, params=params, json=payload)
                        
                        if response.status_code == 200:
                            data = response.json()
                            candidates = data.get("candidates", [])
                            if not candidates:
                                raise ValueError(f"No candidates returned by Gemini model {current_model}")
                            
                            candidate = candidates[0]
                            parts = candidate.get("content", {}).get("parts", [])
                            content = parts[0].get("text", "") if parts else ""

                            usage_meta = data.get("usageMetadata", {})
                            usage = {
                                "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                                "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                                "total_tokens": usage_meta.get("totalTokenCount", 0),
                            }

                            return {
                                "text": content,
                                "metadata": {
                                    "provider": "gemini",
                                    "model": current_model,
                                    "usage": usage,
                                },
                            }
                        elif response.status_code == 402:
                            logger.info(
                                f"Gemini key ({current_key[:8]}...) has depleted prepaid credits (402). Switching to backup key..."
                            )
                            last_error = f"Key {current_key[:8]} depleted prepayment credits (402)"
                            break
                        elif response.status_code in (429, 503, 404):
                            logger.info(
                                f"Gemini model {current_model} returned {response.status_code}, trying next model..."
                            )
                            last_error = f"Model {current_model} returned HTTP {response.status_code}"
                            continue
                        else:
                            logger.error(f"Gemini API error ({response.status_code}): {response.text}")
                            last_error = f"HTTP {response.status_code}: {response.text}"
                            continue

                except httpx.TimeoutException:
                    logger.warning(f"Timeout calling Gemini model {current_model}, trying fallback...")
                    last_error = f"Timeout with {current_model}"
                    continue
                except Exception as e:
                    logger.error(f"Error calling Gemini model {current_model}: {e}")
                    last_error = str(e)
                    continue

        logger.error(f"All Gemini models and keys failed: {last_error}")
        raise RuntimeError(f"Gemini generation failed: {last_error}")
