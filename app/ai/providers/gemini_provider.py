import json
import re
import logging
from typing import Dict, Any

from app.ai.base import AIProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    """
    Google Gemini AI integration using the new google-genai SDK (google.genai).
    Reads GEMINI_API_KEY from config/env.
    """

    def __init__(self):
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing from configuration.")

        try:
            from google import genai
            self._client = genai.Client(api_key=api_key)
        except ImportError:
            raise RuntimeError(
                "google-genai package is not installed. "
                "Run: pip install google-genai"
            )

        # Use a stable, widely available model
        self._model_name = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
        self._provider_name = "gemini"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates text using the new google.genai async client.
        """
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        # If caller wants JSON output, append instruction
        if kwargs.get("response_format", {}).get("type") == "json_object":
            full_prompt += "\n\nRespond ONLY with valid JSON. No markdown, no explanation, no code fences."

        try:
            from google import genai
            from google.genai import types

            response = await self._client.aio.models.generate_content(
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
            logger.error(f"Gemini API Error: {str(e)}")
            raise RuntimeError(f"AI generation failed (Gemini): {str(e)}")

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str = None,
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
