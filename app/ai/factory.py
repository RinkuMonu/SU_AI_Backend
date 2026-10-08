from app.core.config import settings
from app.ai.base import AIProvider
from app.ai.providers.mock import MockAIProvider

class AIProviderFactory:
    """
    Factory to retrieve the configured AI Provider.
    """
    
    _instances = {}

    @classmethod
    def get_provider(cls) -> AIProvider:
        provider_name = settings.AI_PROVIDER.lower()
        
        if provider_name in cls._instances:
            return cls._instances[provider_name]
            
        if provider_name == "mock":
            provider = MockAIProvider()
        elif provider_name == "groq":
            from app.ai.providers.groq_provider import GroqProvider
            provider = GroqProvider()
        elif provider_name == "gemini":
            from app.ai.providers.gemini_provider import GeminiProvider
            provider = GeminiProvider()
        else:
            # Fallback to mock for development safety if configured incorrectly
            provider = MockAIProvider()
            
        cls._instances[provider_name] = provider
        return provider