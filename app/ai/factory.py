import logging
from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider

logger = logging.getLogger(__name__)

class AIProviderFactory:
    """
    Factory to retrieve the configured AI Provider.
    """
    _instances = {}

    @classmethod
    def get_provider(cls, preferred: str = None) -> AIProvider:
        if preferred and preferred.lower() == "gemini":
            from app.ai.providers.gemini_provider import GeminiProvider
            return GeminiProvider()
        elif preferred and preferred.lower() == "groq":
            from app.ai.providers.groq_provider import GroqProvider
            return GroqProvider()

        provider_name = (settings.AI_PROVIDER or "gemini").lower()
        
        if provider_name in cls._instances:
            return cls._instances[provider_name]

        provider = None
        try:
            if provider_name == "gemini" and getattr(settings, "GEMINI_API_KEY", None):
                from app.ai.providers.gemini_provider import GeminiProvider
                provider = GeminiProvider()
            elif provider_name == "groq" and getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                provider = GroqProvider()
            elif provider_name == "mock":
                provider = MockAIProvider()
            elif getattr(settings, "GEMINI_API_KEY", None):
                from app.ai.providers.gemini_provider import GeminiProvider
                provider = GeminiProvider()
            elif getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                provider = GroqProvider()
            else:
                logger.info("No AI API keys configured. Falling back to MockAIProvider.")
                provider = MockAIProvider()
        except Exception as e:
            logger.warning(f"AI Provider failed to initialize ({e}). Falling back to MockAIProvider.")
            provider = MockAIProvider()

        cls._instances[provider_name] = provider
        return provider
