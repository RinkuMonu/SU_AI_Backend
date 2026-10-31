import logging
from typing import Optional
from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider
from app.ai.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class AIProviderFactory:
    """
    Factory to retrieve the centralized OpenAI Provider.
    Enforces OpenAI as the primary and only AI provider.
    - Text & Analysis: gpt-4.1-mini
    - Image & Photoshoot: gpt-image-1-mini
    """
    _instances = {}

    @classmethod
    def get_provider(
        cls,
        preferred: Optional[str] = None,
        tier: str = "fast",
        model: Optional[str] = None
    ) -> AIProvider:
        provider_name = (preferred or settings.AI_PROVIDER or "openai").lower()
        if provider_name == "gemini":
            # Direct seamless routing away from deprecated gemini
            provider_name = "openai"

        cache_key = f"{provider_name}_{tier}_{model or 'default'}"
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        provider = None
        try:
            if provider_name == "mock":
                provider = MockAIProvider()
            elif provider_name == "groq" and getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                provider = GroqProvider()
            else:
                provider = OpenAIProvider(tier=tier, model=model)
        except Exception as e:
            logger.warning(f"AI Provider failed to initialize ({e}). Falling back to MockAIProvider.")
            provider = MockAIProvider()

        cls._instances[cache_key] = provider
        return provider
