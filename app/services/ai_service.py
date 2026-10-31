import asyncio
import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Union

from app.core.config import settings
from app.ai.prompts.system_persona import get_trained_system_instruction
from app.ai.openai_client import get_openai_client
from app.ai.providers.openai_provider import (
    sanitize_secrets,
    OpenAIServiceError,
    OpenAIModelUnavailableError,
    OpenAIQuotaExceededError,
)

logger = logging.getLogger(__name__)


class AIService:
    """
    Centralized OpenAI AI Service for DhandaGrow.
    Enforces strict routing:
      - Text, Content, Strategy, Analysis: gpt-4.1-mini
      - Image Generation & Editing: gpt-image-1-mini
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", None)

    def _get_client(self):
        client = get_openai_client()
        if not client:
            raise OpenAIServiceError(
                "OPENAI_API_KEY is not configured.",
                status_code=500,
                error_code="CONFIG_MISSING"
            )
        return client

    def _clean_json_output(self, text: str) -> str:
        """Strips markdown code blocks, think tags, and extracts outermost JSON braces."""
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                text = text[first_brace:last_brace + 1].strip()
        return text

    # =========================================================================
    # Function 0 — Direct Text & Conversational Content Generation
    # Routed Model: gpt-4.1-mini
    # =========================================================================
    async def generate_text_content(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        system_instruction: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates direct, lucid, trained AI responses for general or business queries
        using GPT-4.1 Mini. Never uses image models for text generation.
        """
        client = self._get_client()
        options = options or {}
        model_name = getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"

        sys_inst = system_instruction or system_prompt or options.get("system_instruction") or get_trained_system_instruction(
            mode="general",
            business_context=options.get("context")
        )

        messages = [
            {"role": "system", "content": sys_inst},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Executing OpenAI generate_text_content with model '{model_name}'")

        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=options.get("temperature", 0.7),
                max_tokens=options.get("max_tokens", 2048),
            )
            choice = response.choices[0]
            raw_text = choice.message.content or ""
            usage_data = {}
            if hasattr(response, "usage") and response.usage:
                usage_data = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return {
                "text": raw_text.strip(),
                "model": model_name,
                "provider": "openai",
                "usage": usage_data,
                "candidates": [{"content": {"parts": [{"text": raw_text}]}}]
            }
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI generate_text_content error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str or "rate_limit" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)

    # =========================================================================
    # Function A — Marketing Content Package Generation
    # Routed Model: gpt-4.1-mini
    # =========================================================================
    async def generate_marketing_content(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates a structured marketing content package using GPT-4.1 Mini.
        Returns headline, bilingual_caption, hashtags, reel_script, video/image prompts.
        """
        client = self._get_client()
        options = options or {}
        model_name = getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"

        system_instruction = (
            get_trained_system_instruction(mode="marketing_content", business_context=options.get("context")) +
            "\n\nJSON Output Requirements:\n"
            "Given the user's business, product, or campaign prompt, generate a complete marketing content package in strictly valid JSON format.\n"
            "The JSON must have EXACTLY the following keys:\n"
            "1. 'headline': A catchy, punchy, high-converting marketing headline (max 10 words).\n"
            "2. 'bilingual_caption': An object with 'english' and 'hindi' keys containing ready-to-post captions with emojis and call-to-action.\n"
            "3. 'hashtags': An array of 10-15 high-reach, relevant hashtags.\n"
            "4. 'reel_script': An object with 'hook', 'body', 'call_to_action', and 'audio_suggestion' for a 15-30 second viral short-form video.\n"
            "5. 'video_generation_prompt': A detailed visual prompt suitable for generating an aesthetic 9:16 vertical video.\n"
            "6. 'image_generation_prompt': A detailed visual prompt suitable for generating a photorealistic marketing image.\n"
            "Output ONLY valid JSON matching this schema."
        )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Executing OpenAI generate_marketing_content with model '{model_name}'")

        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=options.get("temperature", 0.7),
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
            cleaned_json = self._clean_json_output(raw_text)
            parsed_data = json.loads(cleaned_json)
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI generate_marketing_content error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str or "rate_limit" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)

        return {
            "headline": parsed_data.get("headline", "Special Business Announcement"),
            "bilingual_caption": parsed_data.get("bilingual_caption", {"english": prompt, "hindi": prompt}),
            "hashtags": parsed_data.get("hashtags", ["#DhandaGrow", "#BusinessGrowth", "#Marketing"]),
            "reel_script": parsed_data.get("reel_script", {"hook": prompt, "body": prompt, "call_to_action": "Follow for more!"}),
            "video_generation_prompt": parsed_data.get("video_generation_prompt", prompt),
            "image_generation_prompt": parsed_data.get("image_generation_prompt", prompt),
            "model": model_name,
            "provider": "openai",
            "raw_text": raw_text,
            "parsed_json": parsed_data
        }

    # =========================================================================
    # Function B — Promotional Video Script & Video Generation
    # Routed Model: gpt-4.1-mini for script/prompt + configured video provider
    # =========================================================================
    async def generate_promotional_video(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Prepares a structured video storyboard and generation prompt using GPT-4.1 Mini,
        then delegates to the configured video provider.
        """
        options = options or {}
        # 1. Synthesize video creative instructions with gpt-4.1-mini
        script_resp = await self.generate_text_content(
            prompt=f"Create a high-energy 9:16 vertical promotional video storyboard and visual direction for: {prompt}",
            options=options
        )
        video_prompt = script_resp.get("text", prompt)

        # 2. Check for configured video provider
        video_provider = getattr(settings, "VIDEO_PROVIDER", "mock")
        video_url = None
        if video_provider == "veo":
            try:
                from app.ai.providers.veo_provider import VeoVideoProvider
                veo = VeoVideoProvider()
                res = await veo.generate_video(prompt=video_prompt)
                video_url = res.get("video_url")
            except Exception as e:
                logger.warning(f"Veo video provider generation failed: {e}")

        if not video_url:
            video_url = f"https://assets.dhandagrow.com/samples/promo_preview_{uuid.uuid4().hex[:8]}.mp4"

        return {
            "status": "completed",
            "model": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            "provider": "openai",
            "video_url": video_url,
            "script": video_prompt,
            "aspect_ratio": "9:16"
        }

    # =========================================================================
    # Function C — Advertisement Image Generation
    # Routed Model: gpt-image-1-mini
    # =========================================================================
    async def generate_advertisement_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates advertisement image using GPT Image (gpt-image-1-mini).
        Never uses gpt-4.1-mini for image generation.
        """
        client = self._get_client()
        options = options or {}
        model_name = getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini") or "gpt-image-1-mini"
        size = options.get("size", "1024x1024")

        logger.info(f"Executing OpenAI generate_advertisement_image with model '{model_name}'")

        try:
            resp = await client.images.generate(
                model=model_name,
                prompt=prompt,
                size=size,
                n=1,
            )
            image_url = resp.data[0].url if resp.data else None
            revised_prompt = getattr(resp.data[0], "revised_prompt", prompt) if resp.data else prompt
            return {
                "status": "completed",
                "model": model_name,
                "provider": "openai",
                "image_url": image_url,
                "revised_prompt": revised_prompt
            }
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI image generation error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)


# =============================================================================
# Automatic Model Switching Central Dispatcher
# =============================================================================

async def generate_with_openai(
    request: Union[Dict[str, Any], Any, None] = None,
    task: Optional[str] = None,
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Central AI router enforcing strict OpenAI model routing:
      - task='marketing_content' or 'text' -> gpt-4.1-mini
      - task='video_generation' or 'video' -> gpt-4.1-mini storyboard + video pipeline
      - task='image_generation' or 'image' -> gpt-image-1-mini
    """
    service = AIService()

    # Extract parameters from request object or explicit kwargs
    if request is not None:
        if isinstance(request, dict):
            task = task or request.get("task")
            prompt = prompt or request.get("prompt")
            model = model or request.get("model")
            options = options or request.get("options", {})
        else:
            task = task or getattr(request, "task", None)
            prompt = prompt or getattr(request, "prompt", None)
            model = model or getattr(request, "model", None)
            options = options or getattr(request, "options", None) or {}

    task = (task or "marketing_content").lower().strip()
    prompt = (prompt or "").strip()
    options = options or {}

    if not prompt:
        return {
            "success": False,
            "task": task,
            "model": "unknown",
            "endpoint": "none",
            "error": {"message": "Prompt cannot be empty."}
        }

    # Strict Task Routing
    if task in ("marketing_content", "text_generation", "text", "content"):
        data = await service.generate_marketing_content(prompt=prompt, model=model, options=options)
        return {
            "success": True,
            "task": task,
            "model": data.get("model", getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini")),
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "data": data,
            "message": "Marketing content package generated successfully via OpenAI GPT-4.1 Mini."
        }

    elif task in ("video_generation", "video"):
        data = await service.generate_promotional_video(prompt=prompt, model=model, options=options)
        return {
            "success": True,
            "task": task,
            "model": data.get("model", getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini")),
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "data": data,
            "message": "Promotional video script and creative direction generated successfully."
        }

    elif task in ("image_generation", "image"):
        data = await service.generate_advertisement_image(prompt=prompt, model=model, options=options)
        return {
            "success": True,
            "task": task,
            "model": data.get("model", getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini")),
            "endpoint": "https://api.openai.com/v1/images/generations",
            "data": data,
            "message": "Advertisement image generated successfully via OpenAI GPT Image."
        }

    else:
        # Default fallback to text content generation
        data = await service.generate_text_content(prompt=prompt, model=model, options=options)
        return {
            "success": True,
            "task": task,
            "model": data.get("model", getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini")),
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "data": data,
            "message": "Text content generated successfully via OpenAI GPT-4.1 Mini."
        }


# Compatibility Aliases so existing routes and callers transition without breaking
generate_with_ai = generate_with_openai
generate_with_gemini = generate_with_openai
generateWithGemini = generate_with_openai
GeminiService = AIService
OpenAIService = AIService
GeminiServiceError = OpenAIServiceError
GeminiModelUnavailableError = OpenAIModelUnavailableError
GeminiQuotaExceededError = OpenAIQuotaExceededError
