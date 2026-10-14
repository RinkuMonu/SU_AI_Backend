from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider

class AIProviderFactory:
    """
    Factory to retrieve the configured AI Provider.
    """
    
    @classmethod
    def get_provider(cls, preferred: str = None) -> AIProvider:
        if preferred and preferred.lower() == "gemini":
            from app.ai.providers.gemini_provider import GeminiProvider
            return GeminiProvider()
        elif preferred and preferred.lower() == "groq":
            from app.ai.providers.groq_provider import GroqProvider
            return GroqProvider()

        provider_name = settings.AI_PROVIDER.lower()
            
        if provider_name == "gemini":
            from app.ai.providers.gemini_provider import GeminiProvider
            provider = GeminiProvider()
        elif provider_name == "groq":
            from app.ai.providers.groq_provider import GroqProvider
            provider = GroqProvider()
        elif provider_name == "mock":
            provider = MockAIProvider()
        elif settings.GEMINI_API_KEY:
            from app.ai.providers.gemini_provider import GeminiProvider
            provider = GeminiProvider()
        elif settings.GROQ_API_KEY:
            from app.ai.providers.groq_provider import GroqProvider
            provider = GroqProvider()
        else:
            # Fallback to mock for development safety if configured incorrectly
            provider = MockAIProvider()
            
        return provider