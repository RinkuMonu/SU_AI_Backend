"""
Centralized OpenAI Client Factory & Resilience.
Provides AsyncOpenAI client instances configured with backend environment settings.
"""

import logging
from typing import Optional, Any
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_openai_client() -> Optional[Any]:
    """Returns an initialized AsyncOpenAI client if OPENAI_API_KEY is configured."""
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        return None
    try:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=api_key.strip(), timeout=60.0)
    except Exception as e:
        logger.warning(f"Failed to initialize AsyncOpenAI client: {e}")
        return None


def get_sync_openai_client() -> Optional[Any]:
    """Returns an initialized synchronous OpenAI client if OPENAI_API_KEY is configured."""
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key.strip(), timeout=60.0)
    except Exception as e:
        logger.warning(f"Failed to initialize OpenAI client: {e}")
        return None
