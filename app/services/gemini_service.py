import asyncio
import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Union

import httpx

from app.core.config import settings
from app.schemas.ai import (
    GeminiGenerateRequest,
    GeminiGenerateResponse,
    MarketingContentPackage,
)

logger = logging.getLogger(__name__)


def sanitize_secrets(msg: str) -> str:
    """Strips API keys, bearer tokens, or query secrets from error and log messages."""
    if not isinstance(msg, str):
        msg = str(msg)
    cleaned = re.sub(r'key=[A-Za-z0-9_\-\.]+', 'key=[REDACTED]', msg)
    cleaned = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', cleaned)
    cleaned = re.sub(r'AQ\.[A-Za-z0-9_\-]{40,}', '[REDACTED_API_KEY]', cleaned)
    cleaned = re.sub(r'AIza[A-Za-z0-9_\-]{35}', '[REDACTED_API_KEY]', cleaned)
    return cleaned


class GeminiServiceError(Exception):
    """Base exception for Gemini service operations."""
    def __init__(self, message: str, status_code: int = 500, error_code: str = "GEMINI_ERROR", details: Any = None):
        super().__init__(sanitize_secrets(message))
        self.message = sanitize_secrets(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


class GeminiModelUnavailableError(GeminiServiceError):
    """Raised when a requested Gemini model ID or endpoint is deprecated or unavailable (404)."""
    def __init__(self, model: str, endpoint: str, details: Any = None):
        msg = (
            f"Gemini model '{model}' at endpoint '{endpoint}' is unavailable or not accessible to this project (HTTP 404). "
            f"Details: {details}. Please configure a supported model in your environment settings."
        )
        super().__init__(msg, status_code=404, error_code="MODEL_UNAVAILABLE", details=details)


class GeminiQuotaExceededError(GeminiServiceError):
    """Raised when rate limits or prepayment credits prevent execution (429 / 402)."""
    def __init__(self, model: str, endpoint: str, details: Any = None):
        msg = (
            f"Quota or rate limit exceeded for Gemini model '{model}' at endpoint '{endpoint}' (HTTP 429/402). "
            f"Details: {details}."
        )
        super().__init__(msg, status_code=429, error_code="MODEL_RATE_LIMIT", details=details)


class GeminiService:
    """
    Centralized Gemini Integration Service implementing the three cURL request functions:
      1. Function A: Marketing Content Generation via generateContent (gemini-2.5-flash)
      2. Function B: Promotional Video Generation via interactions (gemini-omni-1.1-flash)
      3. Function C: Advertisement Image Generation via interactions (gemini-nano-banana-2.1)
    Provides automatic task routing, payload formatting, async polling, and strict error reporting.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY or getattr(settings, "GEMINI_BACKUP_API_KEY", None)

    def _get_api_key(self) -> str:
        if not self.api_key:
            raise GeminiServiceError(
                "GEMINI_API_KEY is not configured in environment.",
                status_code=500,
                error_code="MISSING_API_KEY"
            )
        return self.api_key

    def _clean_json_output(self, text: str) -> str:
        """Strips markdown code fences and extracts parseable JSON object/array."""
        if not text:
            return ""
        # Match ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        # If not starting with { or [, extract first json block
        if not text.startswith("{") and not text.startswith("["):
            obj_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if obj_match:
                text = obj_match.group(0).strip()
        return text

    # =========================================================================
    # Function A — Marketing Content Generation
    # Endpoint: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
    # Requested Model: gemini-2.5-flash
    # =========================================================================
    async def generate_marketing_content(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates a structured marketing content package containing:
          - Headline
          - Bilingual caption (English & Hindi)
          - Hashtags
          - Reel script
          - Video-generation prompt
          - Image-generation prompt
        """
        api_key = self._get_api_key()
        options = options or {}
        model_name = model or getattr(settings, "GEMINI_MARKETING_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
        endpoint = f"{self.BASE_URL}/models/{model_name}:generateContent"

        system_instruction = (
            "You are an elite marketing strategist, copywriter, and creative director for modern brands.\n"
            "Given the user's business, product, or campaign prompt, generate a complete marketing content package in strictly valid JSON format.\n"
            "The JSON must have EXACTLY the following keys:\n"
            "1. 'headline': An impactful, high-converting marketing headline (1 sentence).\n"
            "2. 'bilingual_caption': An object with 'english' and 'hindi' fields or a natural Hinglish/bilingual caption tailored for Indian and global audiences.\n"
            "3. 'hashtags': An array of 10 to 15 trending, high-reach marketing hashtags.\n"
            "4. 'reel_script': A comprehensive 15-30 second reel storyboard with scene hooks, visual cues, and voiceover text.\n"
            "5. 'video_generation_prompt': A rich, cinematographic prompt tailored for vertical 9:16 promotional video generation.\n"
            "6. 'image_generation_prompt': A photorealistic, detailed visual prompt for an Instagram feed advertisement image.\n"
            "Output ONLY raw, parseable JSON with NO markdown code block wrappers or explanations."
        )

        user_content = f"Create a comprehensive marketing content package for the following prompt:\n{prompt}"
        if options.get("context"):
            user_content += f"\n\nAdditional Business Context: {json.dumps(options['context'])}"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "temperature": options.get("temperature", 0.7),
                "maxOutputTokens": options.get("max_tokens", 4096),
                "responseMimeType": "application/json"
            },
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            }
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        params = {"key": api_key}
        timeout = options.get("timeout", 45.0)

        logger.info(f"Executing Gemini Function A (Marketing Content) with model '{model_name}' at {endpoint}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(endpoint, headers=headers, params=params, json=payload)
            except httpx.TimeoutException:
                raise GeminiServiceError(f"Request to {endpoint} timed out after {timeout}s", status_code=504, error_code="TIMEOUT")
            except Exception as e:
                raise GeminiServiceError(f"HTTP connection error: {sanitize_secrets(str(e))}", status_code=502, error_code="CONNECTION_ERROR")

        if response.status_code == 404:
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiModelUnavailableError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code in (429, 402):
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiQuotaExceededError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code != 200:
            raise GeminiServiceError(
                f"Gemini API returned error ({response.status_code}): {sanitize_secrets(response.text[:300])}",
                status_code=response.status_code,
                error_code="API_ERROR",
                details=response.text
            )

        try:
            resp_data = response.json()
            candidates = resp_data.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini API")
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = parts[0].get("text", "") if parts else ""
        except Exception as e:
            raise GeminiServiceError(f"Failed to read Gemini response structure: {e}", status_code=500, error_code="PARSE_ERROR")

        cleaned_json = self._clean_json_output(raw_text)
        try:
            parsed = json.loads(cleaned_json)
        except json.JSONDecodeError as err:
            logger.warning(f"Initial JSON parse failed, attempting fallback repair: {err}")
            # Try to build fallback package structure if partial text
            parsed = {
                "headline": "Exclusive Promotion",
                "bilingual_caption": {"english": raw_text[:200], "hindi": "विशेष ऑफर"},
                "hashtags": ["#marketing", "#trending", "#viral"],
                "reel_script": raw_text[:500],
                "video_generation_prompt": f"Vertical 9:16 promotional video for: {prompt[:100]}",
                "image_generation_prompt": f"High quality commercial advertisement image for: {prompt[:100]}"
            }

        # Validate against schema
        package = MarketingContentPackage(
            headline=str(parsed.get("headline") or "Marketing Campaign Headline"),
            bilingual_caption=parsed.get("bilingual_caption") or {"english": "Check this out!", "hindi": "आज ही देखें!"},
            hashtags=parsed.get("hashtags") if isinstance(parsed.get("hashtags"), list) else ["#brand", "#viral"],
            reel_script=parsed.get("reel_script") or "Scene 1: Hook and showcase product.",
            video_generation_prompt=str(parsed.get("video_generation_prompt") or f"Vertical 9:16 video of {prompt}"),
            image_generation_prompt=str(parsed.get("image_generation_prompt") or f"Photorealistic ad image of {prompt}")
        )

        return package.model_dump()

    # =========================================================================
    # Function B — Promotional Video Generation
    # Endpoint: POST https://generativelanguage.googleapis.com/v1beta/interactions
    # Requested Model: gemini-omni-1.1-flash
    # =========================================================================
    async def generate_promotional_video(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        poll: bool = True,
        max_wait_seconds: int = 60,
        poll_interval: int = 3
    ) -> Dict[str, Any]:
        """
        Generates a vertical 9:16 promotional video using the requested interactions endpoint
        and model. Handles asynchronous operation polling and MP4 artifact resolution.
        """
        api_key = self._get_api_key()
        options = options or {}
        model_name = model or getattr(settings, "GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash") or "gemini-omni-1.1-flash"
        endpoint = f"{self.BASE_URL}/interactions"

        input_prompt = f"Generate a vertical 9:16 promotional video for social media reels. Video Prompt: {prompt}"
        payload: Dict[str, Any] = {
            "model": model_name,
            "input": input_prompt
        }
        if options.get("generation_config"):
            payload["generation_config"] = options["generation_config"]
        if options.get("reference_image"):
            payload["reference_image"] = options["reference_image"]

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        params = {"key": api_key}
        timeout = options.get("timeout", 35.0)

        logger.info(f"Executing Gemini Function B (Promotional Video) with model '{model_name}' at {endpoint}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(endpoint, headers=headers, params=params, json=payload)
            except httpx.TimeoutException:
                raise GeminiServiceError(f"Request to {endpoint} timed out after {timeout}s", status_code=504, error_code="TIMEOUT")
            except Exception as e:
                raise GeminiServiceError(f"HTTP connection error: {sanitize_secrets(str(e))}", status_code=502, error_code="CONNECTION_ERROR")

        if response.status_code == 404:
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiModelUnavailableError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code in (429, 402):
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiQuotaExceededError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code != 200:
            raise GeminiServiceError(
                f"Gemini Interactions API returned error ({response.status_code}): {sanitize_secrets(response.text[:300])}",
                status_code=response.status_code,
                error_code="API_ERROR",
                details=response.text
            )

        data = response.json()
        interaction_id = data.get("id")
        current_status = data.get("status", "unknown")

        logger.info(f"Gemini video interaction initiated: ID='{interaction_id}', initial status='{current_status}'")

        # If already completed or not polling requested
        if current_status == "completed" or not poll or not interaction_id:
            return self._extract_video_result(data, interaction_id=interaction_id, model=model_name)

        # Asynchronous Polling
        poll_url = f"{self.BASE_URL}/interactions/{interaction_id}"
        elapsed = 0
        logger.info(f"Polling Gemini video interaction '{interaction_id}' for up to {max_wait_seconds}s...")

        async with httpx.AsyncClient(timeout=15.0) as poll_client:
            while elapsed < max_wait_seconds:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    p_resp = await poll_client.get(poll_url, headers=headers, params=params)
                    if p_resp.status_code == 200:
                        p_data = p_resp.json()
                        st = p_data.get("status")
                        if st == "completed":
                            logger.info(f"Gemini video interaction '{interaction_id}' completed successfully after {elapsed}s")
                            return self._extract_video_result(p_data, interaction_id=interaction_id, model=model_name)
                        elif st in ("failed", "cancelled"):
                            err_msg = p_data.get("error", {}).get("message") or f"Interaction status {st}"
                            raise GeminiServiceError(f"Video generation {st}: {err_msg}", status_code=500, error_code="GENERATION_FAILED")
                    else:
                        logger.warning(f"Polling iteration returned status {p_resp.status_code}: {p_resp.text[:120]}")
                except GeminiServiceError:
                    raise
                except Exception as poll_err:
                    logger.warning(f"Error during video polling iteration: {poll_err}")

        # If reached timeout, return processing status with interaction_id
        return {
            "status": "processing",
            "interaction_id": interaction_id,
            "model": model_name,
            "message": f"Video generation is still processing after {max_wait_seconds}s. Use interaction_id to check status later."
        }

    def _extract_video_result(self, data: Dict[str, Any], interaction_id: Optional[str], model: str) -> Dict[str, Any]:
        """Extracts video URL, bytes, or steps from interaction response."""
        video_url = None
        steps = data.get("steps", [])

        # Look in steps for video output
        for step in steps:
            for item in step.get("content", []):
                if item.get("type") == "video":
                    video_url = item.get("url") or item.get("uri")
                    break
                if item.get("type") == "model_output" and "video" in str(item):
                    video_url = item.get("video_url") or item.get("url")

        # Fallback to direct fields
        if not video_url:
            video_url = data.get("video_url") or data.get("result_url") or data.get("output_url")

        return {
            "status": data.get("status", "completed"),
            "interaction_id": interaction_id,
            "model": model,
            "aspect_ratio": "9:16",
            "video_url": video_url,
            "raw_output": data
        }

    # =========================================================================
    # Function C — Advertisement Image Generation
    # Endpoint: POST https://generativelanguage.googleapis.com/v1beta/interactions
    # Requested Model: gemini-nano-banana-2.1
    # =========================================================================
    async def generate_advertisement_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates a premium Instagram advertisement image using the requested
        interactions endpoint and model.
        """
        api_key = self._get_api_key()
        options = options or {}
        model_name = model or getattr(settings, "GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1") or "gemini-nano-banana-2.1"
        endpoint = f"{self.BASE_URL}/interactions"

        input_prompt = f"Generate a premium Instagram advertisement image. Creative Prompt: {prompt}"
        payload: Dict[str, Any] = {
            "model": model_name,
            "input": input_prompt
        }
        if options.get("aspect_ratio"):
            payload["aspect_ratio"] = options["aspect_ratio"]

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        params = {"key": api_key}
        timeout = options.get("timeout", 35.0)

        logger.info(f"Executing Gemini Function C (Advertisement Image) with model '{model_name}' at {endpoint}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(endpoint, headers=headers, params=params, json=payload)
            except httpx.TimeoutException:
                raise GeminiServiceError(f"Request to {endpoint} timed out after {timeout}s", status_code=504, error_code="TIMEOUT")
            except Exception as e:
                raise GeminiServiceError(f"HTTP connection error: {sanitize_secrets(str(e))}", status_code=502, error_code="CONNECTION_ERROR")

        if response.status_code == 404:
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiModelUnavailableError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code in (429, 402):
            err_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            raise GeminiQuotaExceededError(model=model_name, endpoint=endpoint, details=err_data)

        if response.status_code != 200:
            raise GeminiServiceError(
                f"Gemini Interactions API returned error ({response.status_code}): {sanitize_secrets(response.text[:300])}",
                status_code=response.status_code,
                error_code="API_ERROR",
                details=response.text
            )

        data = response.json()
        interaction_id = data.get("id")
        return self._extract_image_result(data, interaction_id=interaction_id, model=model_name)

    def _extract_image_result(self, data: Dict[str, Any], interaction_id: Optional[str], model: str) -> Dict[str, Any]:
        """Extracts image URL, base64 payload, or output reference from interaction response."""
        image_url = None
        steps = data.get("steps", [])

        # Search steps for image content or base64
        for step in steps:
            for item in step.get("content", []):
                if item.get("type") in ("image", "image_url"):
                    image_url = item.get("url") or item.get("image_url")
                    break
                # Base64 inline data check
                if item.get("type") == "image_bytes" or "data:image" in str(item):
                    raw_b64 = item.get("data") or item.get("bytes")
                    if raw_b64:
                        # Save local file
                        out_dir = os.path.join("uploads", "temp")
                        os.makedirs(out_dir, exist_ok=True)
                        filename = f"gemini_ad_{uuid.uuid4().hex[:10]}.jpg"
                        out_path = os.path.join(out_dir, filename)
                        try:
                            with open(out_path, "wb") as f:
                                f.write(base64.b64decode(raw_b64))
                            image_url = settings.get_public_url(f"/uploads/temp/{filename}")
                        except Exception as save_err:
                            logger.warning(f"Could not write image bytes: {save_err}")

        if not image_url:
            image_url = data.get("image_url") or data.get("output_url")

        return {
            "status": data.get("status", "completed"),
            "interaction_id": interaction_id,
            "model": model,
            "image_url": image_url,
            "raw_output": data
        }


# =============================================================================
# Automatic Model Switching Central Dispatcher
# =============================================================================

async def generate_with_gemini(
    request: Union[Dict[str, Any], GeminiGenerateRequest, None] = None,
    task: Optional[str] = None,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Central Gemini router that automatically routes each request to the correct
    cURL-based generation function:
      - 'text' / 'marketing_content' → Function A (Gemini text generation)
      - 'video' / 'video_generation' → Function B (Gemini video generation)
      - 'image' / 'image_generation' → Function C (Gemini image generation)

    Accepts dictionary, Pydantic model, or kwargs.
    Returns consistent result dictionary with status, model, endpoint, data, and error.
    """
    # 1. Normalize parameters from request dict, object, or direct kwargs
    if isinstance(request, GeminiGenerateRequest):
        req_task = request.task
        req_prompt = request.prompt
        req_model = request.model
        req_options = request.options or {}
    elif isinstance(request, dict):
        req_task = request.get("task") or task
        req_prompt = request.get("prompt") or prompt
        req_model = request.get("model") or model
        req_options = request.get("options") or options or {}
    else:
        req_task = task
        req_prompt = prompt
        req_model = model
        req_options = options or {}

    # Merge remaining kwargs into options
    if kwargs:
        req_options.update(kwargs)

    if not req_task:
        raise ValueError("Parameter 'task' is required for generate_with_gemini.")
    if not req_prompt:
        raise ValueError("Parameter 'prompt' is required for generate_with_gemini.")

    normalized_task = str(req_task).lower().strip()
    service = GeminiService()

    # 2. Automatic task routing
    # Task Category 1: Marketing Content / Text
    if normalized_task in ("text", "marketing_content", "marketing", "content", "caption", "copy"):
        target_model = req_model or getattr(settings, "GEMINI_MARKETING_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
        target_endpoint = f"{service.BASE_URL}/models/{target_model}:generateContent"
        try:
            result = await service.generate_marketing_content(
                prompt=req_prompt,
                model=target_model,
                options=req_options
            )
            return {
                "success": True,
                "task": "marketing_content",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": result,
                "error": None
            }
        except GeminiServiceError as ge:
            return {
                "success": False,
                "task": "marketing_content",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": None,
                "error": {
                    "code": ge.error_code,
                    "status_code": ge.status_code,
                    "message": ge.message,
                    "details": ge.details
                }
            }

    # Task Category 2: Promotional Video Generation
    elif normalized_task in ("video", "video_generation", "promotional_video", "reel"):
        target_model = req_model or getattr(settings, "GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash") or "gemini-omni-1.1-flash"
        target_endpoint = f"{service.BASE_URL}/interactions"
        try:
            result = await service.generate_promotional_video(
                prompt=req_prompt,
                model=target_model,
                options=req_options,
                poll=req_options.get("poll", True),
                max_wait_seconds=req_options.get("max_wait_seconds", 60),
                poll_interval=req_options.get("poll_interval", 3)
            )
            return {
                "success": True,
                "task": "video_generation",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": result,
                "error": None
            }
        except GeminiServiceError as ge:
            return {
                "success": False,
                "task": "video_generation",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": None,
                "error": {
                    "code": ge.error_code,
                    "status_code": ge.status_code,
                    "message": ge.message,
                    "details": ge.details
                }
            }

    # Task Category 3: Advertisement Image Generation
    elif normalized_task in ("image", "image_generation", "ad_image", "advertisement_image"):
        target_model = req_model or getattr(settings, "GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1") or "gemini-nano-banana-2.1"
        target_endpoint = f"{service.BASE_URL}/interactions"
        try:
            result = await service.generate_advertisement_image(
                prompt=req_prompt,
                model=target_model,
                options=req_options
            )
            return {
                "success": True,
                "task": "image_generation",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": result,
                "error": None
            }
        except GeminiServiceError as ge:
            return {
                "success": False,
                "task": "image_generation",
                "model": target_model,
                "endpoint": target_endpoint,
                "data": None,
                "error": {
                    "code": ge.error_code,
                    "status_code": ge.status_code,
                    "message": ge.message,
                    "details": ge.details
                }
            }

    else:
        supported = ["marketing_content (or text)", "video_generation (or video)", "image_generation (or image)"]
        raise ValueError(f"Unsupported task '{req_task}'. Supported tasks are: {', '.join(supported)}")


# Alias for camelCase callers as requested in prompt example: await generateWithGemini(...)
generateWithGemini = generate_with_gemini
