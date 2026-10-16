import json
import re
import logging
from typing import Dict, Any, List, Optional
import httpx

from app.ai.base import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    """
    Google Gemini AI provider supporting both the new google-genai SDK
    and asynchronous HTTP REST fallback with multi-model redundancy.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing from configuration.")

        configured_model = model or getattr(settings, "GEMINI_MODEL", None) or "gemini-3.8-flash"
        self._model_name = configured_model
        self._provider_name = "gemini"

        # Try to initialize google.genai client if installed
        self._genai_client = None
        try:
            from google import genai
            self._genai_client = genai.Client(api_key=self.api_key)
        except Exception:
            self._genai_client = None

        fallback_models = [
            configured_model,
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
        ]
        seen = set()
        self.models_to_try: List[str] = []
        for m in fallback_models:
            if m not in seen:
                seen.add(m)
                self.models_to_try.append(m)

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates text using the official google-genai SDK if available,
        or falls back to httpx REST API.
        """
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        is_json = kwargs.get("response_format", {}).get("type") == "json_object"
        if is_json:
            full_prompt += "\n\nRespond ONLY with valid JSON. No markdown, no explanation, no code fences."

        # Attempt SDK call first if client is available
        if self._genai_client:
            try:
                from google.genai import types

                response = await self._genai_client.aio.models.generate_content(
                    model=self._model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=kwargs.get("temperature", 0.7),
                        max_output_tokens=kwargs.get("max_tokens", 2048),
                    ),
                )
                content = response.text if response.text else ""
                return {
                    "text": content,
                    "metadata": {
                        "provider": self._provider_name,
                        "model": self._model_name,
                        "usage": {},
                    },
                }
            except Exception as e:
                logger.warning(f"Google GenAI SDK call failed: {e}. Falling back to REST API.")

        # Fallback to direct REST API via httpx
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
        for current_model in self.models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent"
            params = {"key": self.api_key}

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
                    elif response.status_code in (429, 503, 404):
                        logger.warning(
                            f"Gemini model {current_model} returned {response.status_code}: {response.text[:120]}, trying fallback..."
                        )
                        last_error = f"Model {current_model} status {response.status_code}"
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

        logger.error(f"All Gemini models failed: {last_error}")
        raise RuntimeError(f"Gemini generation failed: {last_error}")

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Override to ensure robust JSON parsing."""
        kwargs["response_format"] = {"type": "json_object"}
        result = await self.generate_text(prompt, system_prompt, **kwargs)
        text = result.get("text", "").strip()

        # Strip markdown code fences if model ignores instructions
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        # Fallback: find first JSON object/array
        if not text.startswith("{") and not text.startswith("["):
            obj_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if obj_match:
                text = obj_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(f"Gemini JSON parse error: {exc}\nRaw: {text[:500]}")
            return {"error": "Failed to parse JSON", "raw_text": text}
