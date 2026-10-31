"""
Compatibility provider redirecting legacy GeminiProvider requests directly to OpenAIProvider.
Enforces OpenAI GPT-4.1 Mini and GPT Image as the sole engine.
"""

import logging
from typing import Dict, Any, Optional
from app.ai.providers.openai_provider import OpenAIProvider, sanitize_secrets

logger = logging.getLogger(__name__)


class GeminiProvider(OpenAIProvider):
    """
    Legacy GeminiProvider adapter redirected to OpenAIProvider.
    Uses GPT-4.1 Mini for text and GPT Image for images.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        tier: str = "fast",
    ):
        super().__init__(tier=tier, model=model)
