import asyncio
import base64
import io
import json
import logging
import re
from typing import Dict, Any, List, Optional, Union
import httpx

from app.ai.base import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


def sanitize_log_message(msg: str) -> str:
    """Strips API keys, bearer tokens, or URL query secrets from logs."""
    cleaned = re.sub(r'key=[A-Za-z0-9_\-\.]+', 'key=[REDACTED]', msg)
    cleaned = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', cleaned)
    cleaned = re.sub(r'AQ\.[A-Za-z0-9_\-]{40,}', '[REDACTED_API_KEY]', cleaned)
    cleaned = re.sub(r'AIza[A-Za-z0-9_\-]{35}', '[REDACTED_API_KEY]', cleaned)
    return cleaned


class GeminiProvider(AIProvider):
    """
    Production-grade Google Gemini AI provider supporting:
    - Task-based model selection (Tier: 'reasoning' for complex strategic analysis vs 'fast' for high-volume content)
    - Structured JSON outputs with schema enforcement and resilient fence parsing
    - Multimodal text + vision capabilities (inline images without assuming text-to-image)
    - Robust exponential-backoff retries for 429 (rate limits) and 503 (transient unavailability)
    - Clean, safe error messages that never expose API keys or secrets
    - Multi-model fallback redundancy
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        tier: str = "fast",
    ):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing from configuration.")

        self.tier = tier.lower() if tier else "fast"
        if model:
            self._model_name = model
        elif self.tier == "reasoning":
            self._model_name = getattr(settings, "GEMINI_REASONING_MODEL", "gemini-3.8-pro") or "gemini-3.8-pro"
        else:
            self._model_name = getattr(settings, "GEMINI_FAST_MODEL", None) or getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"

        self._provider_name = "gemini"

        # Try to initialize google.genai client if installed
        self._genai_client = None
        try:
            from google import genai
            self._genai_client = genai.Client(api_key=self.api_key)
        except Exception:
            self._genai_client = None

        # Build prioritized fallback list based on model tier
        if self.tier == "reasoning":
            fallback_models = [
                self._model_name,
                "gemini-3.8-pro",
                "gemini-3.1-pro-preview",
                "gemini-3.8-flash",
                "gemini-3.5-flash",
                "gemini-pro-latest",
                "gemini-flash-latest",
            ]
        else:
            fallback_models = [
                self._model_name,
                "gemini-3.8-flash",
                "gemini-3.5-flash",
                "gemini-flash-latest",
                "gemini-flash-lite-latest",
                "gemini-3-flash-preview",
                "gemini-3.8-pro",
            ]

        seen = set()
        self.models_to_try: List[str] = []
        for m in fallback_models:
            if m and m not in seen:
                seen.add(m)
                self.models_to_try.append(m)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _prepare_multimodal_parts(
        self,
        prompt: str,
        images: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Prepares text and image parts for Gemini contents payload."""
        parts: List[Dict[str, Any]] = [{"text": prompt}]

        if not images:
            return parts

        for img in images:
            if img is None:
                continue

            # Case 1: PIL Image
            if hasattr(img, "save"):
                try:
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    parts.append({
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64
                        }
                    })
                    continue
                except Exception as e:
                    logger.warning(sanitize_log_message(f"Failed to encode PIL Image for Gemini: {e}"))
                    continue

            # Case 2: Base64 data URI string
            if isinstance(img, str) and img.startswith("data:image/"):
                try:
                    header, b64_str = img.split(",", 1)
                    mime = header.split(";")[0].replace("data:", "")
                    parts.append({
                        "inlineData": {
                            "mimeType": mime or "image/jpeg",
                            "data": b64_str.strip()
                        }
                    })
                    continue
                except Exception as e:
                    logger.warning(sanitize_log_message(f"Failed to parse base64 data URI: {e}"))
                    continue

            # Case 3: Raw bytes
            if isinstance(img, bytes):
                try:
                    b64 = base64.b64encode(img).decode("utf-8")
                    parts.append({
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64
                        }
                    })
                    continue
                except Exception as e:
                    logger.warning(sanitize_log_message(f"Failed to encode image bytes: {e}"))
                    continue

        return parts

    def _build_payload(
        self,
        prompt: str,
        images: Optional[List[Any]] = None,
        system_instruction: Optional[str] = None,
        is_json: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> Dict[str, Any]:
        """Constructs the standard REST payload for Gemini models."""
        parts = self._prepare_multimodal_parts(prompt, images=images)
        payload: Dict[str, Any] = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        if is_json:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        return payload

    async def _call_api(
        self,
        url: str,
        payload: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 35.0,
    ) -> httpx.Response:
        """Calls the Gemini REST API endpoint with timeout and sanitized logging."""
        request_params = params if params is not None else ({"key": self.api_key} if self.api_key else {})
        api_key = request_params.get("key") or self.api_key
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["x-goog-api-key"] = api_key
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(url, headers=headers, params=request_params, json=payload)

    def _clean_json_output(self, text: str) -> str:
        """Strips markdown code fences and extracts parseable JSON object/array."""
        if not text:
            return ""
        # Strip ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        # If not starting with { or [, extract first json block
        if not text.startswith("{") and not text.startswith("["):
            obj_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if obj_match:
                text = obj_match.group(0).strip()
        return text

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        images: Optional[List[Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates text using Google GenAI SDK if available, or async REST API with
        automatic retries and multi-model fallback.
        """
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        is_json = kwargs.get("response_format", {}).get("type") == "json_object"
        if is_json:
            full_prompt += "\n\nRespond ONLY with valid JSON. No markdown, no explanation, no code fences."

        # Attempt SDK call first if client is available and no custom images passed
        if self._genai_client and not images:
            try:
                from google.genai import types

                response = await self._genai_client.aio.models.generate_content(
                    model=self._model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=kwargs.get("temperature", 0.7),
                        max_output_tokens=kwargs.get("max_tokens", 4096),
                    ),
                )
                content = response.text if response.text else ""
                return {
                    "text": content,
                    "metadata": {
                        "provider": self._provider_name,
                        "model": self._model_name,
                        "tier": self.tier,
                        "usage": {},
                    },
                }
            except Exception as e:
                err_text = str(e)
                if "402" in err_text or "prepayment" in err_text.lower():
                    logger.warning(sanitize_log_message(f"Gemini GenAI SDK credit check: {err_text}"))
                else:
                    logger.warning(sanitize_log_message(f"Google GenAI SDK call fallback to REST: {e}"))

        # Fallback to direct REST API via httpx
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 8192)

        payload = self._build_payload(
            prompt=prompt,
            images=images,
            system_instruction=system_prompt,
            is_json=is_json,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        last_error = None
        credits_depleted = False
        credits_depleted = False
        api_key = self.api_key or getattr(settings, "GEMINI_BACKUP_API_KEY", None)

        for current_model in self.models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent"
            params = {"key": api_key}

            # Retry up to 2 times per model on 429 / 503
            for attempt in range(2):
                try:
                    response = await self._call_api(url, payload=payload, params=params)

                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            raise ValueError(f"No candidates returned by Gemini model {current_model}")

                        candidate = candidates[0]
                        parts_resp = candidate.get("content", {}).get("parts", [])
                        content = parts_resp[0].get("text", "") if parts_resp else ""

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
                                "tier": self.tier,
                                "usage": usage,
                            },
                        }

                    elif response.status_code == 402:
                        credits_depleted = True
                        last_error = "Gemini API prepayment credits are depleted. Please check billing or add credits in Google AI Studio."
                        logger.warning(sanitize_log_message(f"Gemini {current_model} credits depleted (HTTP 402)"))
                        # No need to retry same model on 402
                        break

                    elif response.status_code == 429:
                        last_error = f"Model {current_model} rate limit (HTTP 429)"
                        logger.warning(sanitize_log_message(f"Gemini rate limit 429 on {current_model}, backing off..."))
                        await asyncio.sleep(min(1.5 * (attempt + 1), 4.0))
                        continue

                    elif response.status_code in (503, 502):
                        last_error = f"Model {current_model} service unavailable (HTTP {response.status_code})"
                        logger.warning(sanitize_log_message(f"Gemini 503/502 on {current_model}, retrying..."))
                        await asyncio.sleep(1.0)
                        continue

                    else:
                        last_error = f"HTTP {response.status_code}: {response.text[:120]}"
                        logger.warning(sanitize_log_message(f"Gemini API error ({response.status_code}) on {current_model}"))
                        break

                except httpx.TimeoutException:
                    last_error = f"Timeout with {current_model}"
                    logger.warning(sanitize_log_message(f"Timeout calling Gemini model {current_model}"))
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.error(sanitize_log_message(f"Error calling Gemini model {current_model}: {e}"))
                    break

        clean_err = sanitize_log_message(last_error or "Unknown error")
        logger.error(f"All Gemini models failed. Last error: {clean_err}")
        if credits_depleted:
            raise RuntimeError("Gemini API prepayment credits are depleted. Please check billing or add credits in Google AI Studio.")
        raise RuntimeError(f"Gemini generation failed: {clean_err}")

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        images: Optional[List[Any]] = None,
        schema: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates structured JSON output with validation, markdown fence stripping,
        and fallback object extraction.
        """
        enhanced_system = system_prompt or "You are an expert AI system. Output ONLY valid, parseable JSON."
        if schema:
            enhanced_system += f"\nStrictly follow this JSON schema:\n{json.dumps(schema)}"

        kwargs["response_format"] = {"type": "json_object"}
        result = await self.generate_text(
            prompt=prompt,
            system_prompt=enhanced_system,
            images=images,
            **kwargs
        )
        if isinstance(result, dict):
            text = result.get("text", "").strip()
        else:
            text = str(result).strip()

        text = self._clean_json_output(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(sanitize_log_message(f"Gemini JSON parse error: {exc}\nRaw: {text[:200]}"))
            return {"error": "Failed to parse JSON", "raw_text": text}
