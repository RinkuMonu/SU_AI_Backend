"""
Centralized AI Client Factory.
Re-exported to route all callers to OpenAI.
"""

import logging
from typing import Any, List, Optional
from app.ai.openai_client import get_openai_client, get_sync_openai_client

logger = logging.getLogger(__name__)


def get_gemini_clients() -> List[Any]:
    """Compatibility adapter returning initialized OpenAI client."""
    client = get_openai_client()
    return [client] if client else []


def get_primary_gemini_client() -> Optional[Any]:
    """Compatibility adapter returning primary OpenAI client."""
    return get_openai_client()
