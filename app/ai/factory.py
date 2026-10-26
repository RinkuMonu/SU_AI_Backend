import logging
from typing import Optional
from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider

logger = logging.getLogger(__name__)

class AIProviderFactory:
    """
    Factory to retrieve the configured AI Provider with support for
    fast vs complex reasoning model tiers.
    """
    _instances = {}

    @classmethod
    def get_provider(
        cls,
        preferred: Optional[str] = None,
        tier: str = "fast",
        model: Optional[str] = None
    ) -> AIProvider:
        provider_name = (preferred or settings.AI_PROVIDER or "gemini").lower()
        cache_key = f"{provider_name}_{tier}_{model or 'default'}"
        
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        provider = None
        try:
            if provider_name == "gemini":
                from app.ai.providers.gemini_provider import GeminiProvider
                provider = GeminiProvider(tier=tier, model=model)
            elif provider_name == "groq":
                from app.ai.providers.groq_provider import GroqProvider
                provider = GroqProvider()
            elif provider_name == "mock":
                provider = MockAIProvider()
            elif getattr(settings, "GEMINI_API_KEY", None):
                from app.ai.providers.gemini_provider import GeminiProvider
                provider = GeminiProvider(tier=tier, model=model)
            elif getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                provider = GroqProvider()
            else:
                logger.info("No AI API keys configured. Falling back to MockAIProvider.")
                provider = MockAIProvider()
        except Exception as e:
            logger.warning(f"AI Provider failed to initialize ({e}). Falling back to MockAIProvider.")
            provider = MockAIProvider()

        cls._instances[cache_key] = provider
        return provider
