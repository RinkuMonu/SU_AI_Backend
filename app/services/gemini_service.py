"""
Centralized AI service module re-exported for backward compatibility.
All generation logic is powered exclusively by OpenAI (GPT-4.1 Mini & GPT Image).
"""
from app.services.ai_service import (
    AIService,
    OpenAIService,
    GeminiService,
    OpenAIServiceError,
    OpenAIModelUnavailableError,
    OpenAIQuotaExceededError,
    GeminiServiceError,
    GeminiModelUnavailableError,
    GeminiQuotaExceededError,
    generate_with_openai,
    generate_with_ai,
    generate_with_gemini,
    generateWithGemini,
    sanitize_secrets,
)

__all__ = [
    "AIService",
    "OpenAIService",
    "GeminiService",
    "OpenAIServiceError",
    "OpenAIModelUnavailableError",
    "OpenAIQuotaExceededError",
    "GeminiServiceError",
    "GeminiModelUnavailableError",
    "GeminiQuotaExceededError",
    "generate_with_openai",
    "generate_with_ai",
    "generate_with_gemini",
    "generateWithGemini",
    "sanitize_secrets",
]
