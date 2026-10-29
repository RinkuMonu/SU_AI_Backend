"""
Centralized Gemini Client Factory with Key Failover & Resilience.
Provides google.genai Client instances configured with primary and backup keys.
"""

import logging
from typing import Any, List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


def get_gemini_clients() -> List[Any]:
    """Returns initialized google.genai Client instances for all configured keys."""
    clients = []
    keys = getattr(settings, "get_gemini_api_keys", lambda: [])()
    if not keys and getattr(settings, "GEMINI_API_KEY", None):
        keys = [settings.GEMINI_API_KEY]
    for k in keys:
        if k and isinstance(k, str) and k.strip():
            try:
                from google import genai
                clients.append(genai.Client(api_key=k.strip()))
            except Exception as e:
                logger.warning(f"Failed to initialize google.genai Client: {e}")
    return clients


def get_primary_gemini_client() -> Optional[Any]:
    """Returns the primary client if available, else first working backup client."""
    clients = get_gemini_clients()
    return clients[0] if clients else None
