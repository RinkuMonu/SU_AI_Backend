import json
import re
import logging
from typing import Dict, Any

from app.ai.base import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    """
    Google Gemini AI integration using the google-generativeai SDK.
    Reads GEMINI_API_KEY from config/env.
    """

    def __init__(self):
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai"
            )

        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing from configuration.")

        genai.configure(api_key=api_key)
        model_name = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        self.model = genai.GenerativeModel(model_name)
        self._provider_name = "gemini"
        self._model_name = model_name

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates text using the Gemini API.
        Combines system_prompt + prompt into a single message (Gemini doesn't
        have a separate system-role in the basic API).
        """
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        # If caller wants JSON, append a reminder
        if kwargs.get("response_format", {}).get("type") == "json_object":
            full_prompt += "\n\nRespond ONLY with valid JSON. No markdown, no explanation."

        try:
            generation_config = {
                "temperature": kwargs.get("temperature", 0.7),
                "max_output_tokens": kwargs.get("max_tokens", 2048),
            }

            response = await self.model.generate_content_async(
                full_prompt,
                generation_config=generation_config,
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
            logger.error(f"Gemini API Error: {str(e)}")
            raise RuntimeError(f"AI generation failed (Gemini): {str(e)}")

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Override to strip markdown fences before JSON parsing."""
        kwargs["response_format"] = {"type": "json_object"}
        result = await self.generate_text(prompt, system_prompt, **kwargs)
        text = result.get("text", "")

        # Strip markdown code fences
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        # Strip any leading/trailing non-JSON characters
        text = text.strip()
        if not text.startswith("{") and not text.startswith("["):
            # Try to find JSON object
            obj_match = re.search(r"\{.*\}", text, re.DOTALL)
            if obj_match:
                text = obj_match.group(0)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(f"Gemini JSON parse error: {exc}\nRaw: {text[:500]}")
            return {"error": "Failed to parse JSON", "raw_text": text}
