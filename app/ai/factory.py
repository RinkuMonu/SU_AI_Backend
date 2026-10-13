from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider
import logging

logger = logging.getLogger(__name__)

class AIProviderFactory:
    """
    Factory to retrieve the configured AI Provider.
    """
    
    @classmethod
    def get_provider(cls) -> AIProvider:
        provider_name = (settings.AI_PROVIDER or "gemini").lower()
            
        try:
            if provider_name == "gemini" and getattr(settings, "GEMINI_API_KEY", None):
                from app.ai.providers.gemini_provider import GeminiProvider
                return GeminiProvider()
            elif provider_name == "groq" and getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                return GroqProvider()
            elif provider_name == "mock":
                return MockAIProvider()
            elif getattr(settings, "GEMINI_API_KEY", None):
                from app.ai.providers.gemini_provider import GeminiProvider
                return GeminiProvider()
            elif getattr(settings, "GROQ_API_KEY", None):
                from app.ai.providers.groq_provider import GroqProvider
                return GroqProvider()
            else:
                logger.info("No AI API keys configured. Falling back to MockAIProvider.")
                return MockAIProvider()
        except Exception as e:
            logger.warning(f"AI Provider failed to initialize ({e}). Falling back to MockAIProvider.")
            return MockAIProvider()
