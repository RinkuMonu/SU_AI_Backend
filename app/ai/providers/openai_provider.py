import io
import re
import base64
import json
import logging
from typing import Dict, Any, Optional, List, Union
from PIL import Image

from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.openai_client import get_openai_client

logger = logging.getLogger(__name__)


def sanitize_secrets(msg: str) -> str:
    """Strips API keys, bearer tokens, or query secrets from error and log messages."""
    if not isinstance(msg, str):
        msg = str(msg)
    cleaned = re.sub(r'sk-[A-Za-z0-9_\-\.]{20,}', '[REDACTED_OPENAI_KEY]', msg)
    cleaned = re.sub(r'Bearer\s+[A-Za-z0-9_\-\.]+', 'Bearer [REDACTED]', cleaned)
    return cleaned


class OpenAIServiceError(Exception):
    """Base exception for OpenAI service operations."""
    def __init__(self, message: str, status_code: int = 500, error_code: str = "OPENAI_ERROR", details: Any = None):
        super().__init__(sanitize_secrets(message))
        self.message = sanitize_secrets(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


class OpenAIModelUnavailableError(OpenAIServiceError):
    """Raised when a requested OpenAI model is not accessible or deprecated."""
    def __init__(self, model: str, details: Any = None):
        msg = (
            f"OpenAI model '{model}' is unavailable or not accessible to this account (HTTP 404). "
            f"Details: {details}. Please configure a supported model in your environment settings."
        )
        super().__init__(msg, status_code=404, error_code="MODEL_UNAVAILABLE", details=details)


class OpenAIQuotaExceededError(OpenAIServiceError):
    """Raised when OpenAI rate limit or billing quota is exceeded."""
    def __init__(self, model: str, details: Any = None):
        msg = f"Quota or rate limit exceeded for OpenAI model '{model}' (HTTP 429). Details: {details}."
        super().__init__(msg, status_code=429, error_code="QUOTA_EXCEEDED", details=details)


class OpenAIProvider(AIProvider):
    """
    Centralized OpenAI AI Provider implementing strict routing rules:
      - Text & Content Generation: gpt-4.1-mini
      - Image Generation & Editing: gpt-image-1-mini
    """

    def __init__(
        self,
        tier: str = "fast",
        model: Optional[str] = None,
        image_model: Optional[str] = None
    ):
        self.tier = tier
        self.text_model = model or getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"
        self.image_model = image_model or getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini") or "gpt-image-1-mini"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        images: Optional[List[Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes text or multimodal vision generation using gpt-4.1-mini.
        Never uses image-generation models for text tasks.
        """
        client = get_openai_client()
        if not client:
            raise OpenAIServiceError("OPENAI_API_KEY is not configured.", status_code=500, error_code="CONFIG_MISSING")

        model_name = kwargs.get("model") or self.text_model
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Multimodal user content if images provided
        if images:
            content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                if isinstance(img, str):
                    if img.startswith("data:image"):
                        content_list.append({"type": "image_url", "image_url": {"url": img}})
                    elif img.startswith("http://") or img.startswith("https://"):
                        content_list.append({"type": "image_url", "image_url": {"url": img}})
                    else:
                        # Assume base64 string
                        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})
                elif isinstance(img, bytes):
                    b64 = base64.b64encode(img).decode("utf-8")
                    content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                elif isinstance(img, Image.Image):
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=90)
                    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            messages.append({"role": "user", "content": content_list})
        else:
            messages.append({"role": "user", "content": prompt})

        call_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if "response_format" in kwargs:
            call_kwargs["response_format"] = kwargs["response_format"]
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens

        try:
            response = await client.chat.completions.create(**call_kwargs)
            choice = response.choices[0]
            text = choice.message.content or ""
            usage_data = {}
            if hasattr(response, "usage") and response.usage:
                usage_data = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return {
                "text": text,
                "model": model_name,
                "provider": "openai",
                "usage": usage_data
            }
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI text generation error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str or "rate_limit" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Generates structured JSON using gpt-4.1-mini with response_format json_object."""
        kwargs["response_format"] = {"type": "json_object"}
        res = await self.generate_text(prompt, system_prompt=system_prompt, **kwargs)
        raw_text = res.get("text", "").strip()

        # Clean markdown wrappers if any
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            # Try to find outermost braces
            first_b = cleaned.find("{")
            last_b = cleaned.rfind("}")
            if first_b != -1 and last_b != -1 and last_b > first_b:
                try:
                    return json.loads(cleaned[first_b : last_b + 1])
                except Exception:
                    pass
            return {"error": "Failed to parse JSON response", "raw_text": raw_text}

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generates images using gpt-image-1-mini.
        Never uses gpt-4.1-mini for image generation.
        """
        client = get_openai_client()
        if not client:
            raise OpenAIServiceError("OPENAI_API_KEY is not configured.", status_code=500, error_code="CONFIG_MISSING")

        model_name = kwargs.get("model") or self.image_model

        try:
            resp = await client.images.generate(
                model=model_name,
                prompt=prompt,
                size=size,
                quality=quality,
                n=n,
                response_format=kwargs.get("response_format", "url")
            )
            image_data = []
            for item in resp.data:
                image_data.append({
                    "url": getattr(item, "url", None),
                    "b64_json": getattr(item, "b64_json", None),
                    "revised_prompt": getattr(item, "revised_prompt", None)
                })
            return {
                "success": True,
                "model": model_name,
                "provider": "openai",
                "images": image_data,
                "image_url": image_data[0]["url"] if image_data else None,
                "revised_prompt": image_data[0]["revised_prompt"] if image_data else prompt
            }
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI image generation error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)

    async def edit_image(
        self,
        image: Union[bytes, io.BufferedReader, Any],
        prompt: str,
        mask: Optional[Union[bytes, io.BufferedReader, Any]] = None,
        size: str = "1024x1024",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Edits images using gpt-image-1-mini.
        """
        client = get_openai_client()
        if not client:
            raise OpenAIServiceError("OPENAI_API_KEY is not configured.", status_code=500, error_code="CONFIG_MISSING")

        model_name = kwargs.get("model") or self.image_model

        try:
            call_kwargs = {
                "model": model_name,
                "image": image,
                "prompt": prompt,
                "size": size,
            }
            if mask:
                call_kwargs["mask"] = mask

            resp = await client.images.edit(**call_kwargs)
            image_data = []
            for item in resp.data:
                image_data.append({
                    "url": getattr(item, "url", None),
                    "b64_json": getattr(item, "b64_json", None)
                })
            return {
                "success": True,
                "model": model_name,
                "provider": "openai",
                "images": image_data,
                "image_url": image_data[0]["url"] if image_data else None
            }
        except Exception as e:
            err_str = str(e)
            logger.error(f"OpenAI image edit error: {sanitize_secrets(err_str)}")
            if "404" in err_str or "model_not_found" in err_str:
                raise OpenAIModelUnavailableError(model_name, details=sanitize_secrets(err_str))
            if "429" in err_str or "insufficient_quota" in err_str:
                raise OpenAIQuotaExceededError(model_name, details=sanitize_secrets(err_str))
            raise OpenAIServiceError(sanitize_secrets(err_str), status_code=502)
