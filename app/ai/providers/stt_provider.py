import io
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class STTResult(BaseModel):
    text: str
    detected_language: Optional[str] = None
    duration_seconds: Optional[float] = None
    provider: str
    model: str


class BaseSTTProvider(ABC):
    """Abstract Base Class for Speech-to-Text Providers."""

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> STTResult:
        """
        Transcribes the given audio bytes into text.
        """
        pass





class GroqWhisperSTTProvider(BaseSTTProvider):
    """
    Speech-to-Text provider using Groq Whisper API (whisper-large-v3).
    High-speed transcription with native Hindi, English, and Hinglish support.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "GROQ_API_KEY", None)
        self.model = model_name or getattr(settings, "STT_GROQ_MODEL", "whisper-large-v3")
        self.provider_name = "groq"

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> STTResult:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")

        from groq import AsyncGroq
        client = AsyncGroq(api_key=self.api_key)

        clean_filename = filename if filename and "." in filename else "audio.wav"
        clean_lang = (language or "").strip().lower()
        groq_lang = None
        if clean_lang in ["en", "english", "en-in", "en-us"]:
            groq_lang = "en"
        elif clean_lang in ["hi", "hindi", "hi-in"]:
            groq_lang = "hi"
        # For Hinglish or auto, Whisper auto-detects multilingual code-switching best when language is None

        file_tuple = (clean_filename, audio_bytes, mime_type)

        try:
            transcription = await client.audio.transcriptions.create(
                file=file_tuple,
                model=self.model,
                language=groq_lang,
                prompt=prompt or "Hindi, English, Hinglish business audio transcription for DhandaGrow",
                response_format="verbose_json"
            )
            raw_text = getattr(transcription, "text", "") or ""
            detected_lang = getattr(transcription, "language", clean_lang or "auto")
            duration = getattr(transcription, "duration", None)

            return STTResult(
                text=raw_text.strip(),
                detected_language=detected_lang,
                duration_seconds=float(duration) if duration is not None else None,
                provider=self.provider_name,
                model=self.model
            )
        except Exception as e:
            logger.error(f"Groq Whisper STT error: {e}")
            raise RuntimeError(f"Groq Whisper transcription failed: {e}")


class OpenAIWhisperSTTProvider(BaseSTTProvider):
    """
    Speech-to-Text provider using OpenAI Whisper API.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", None)
        self.model = model_name or getattr(settings, "STT_OPENAI_MODEL", "whisper-1")
        self.provider_name = "openai"

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> STTResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        import httpx
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        clean_filename = filename if filename and "." in filename else "audio.wav"
        clean_lang = (language or "").strip().lower()
        openai_lang = "hi" if clean_lang in ["hi", "hindi"] else ("en" if clean_lang in ["en", "english"] else None)

        data = {"model": self.model}
        if openai_lang:
            data["language"] = openai_lang
        if prompt:
            data["prompt"] = prompt

        files = {"file": (clean_filename, audio_bytes, mime_type)}

        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(url, headers=headers, data=data, files=files)
            if res.status_code >= 400:
                raise RuntimeError(f"OpenAI Whisper API error (HTTP {res.status_code}): {res.text}")
            res_json = res.json()
            return STTResult(
                text=(res_json.get("text") or "").strip(),
                detected_language=clean_lang or "auto",
                provider=self.provider_name,
                model=self.model
            )


class MockSTTProvider(BaseSTTProvider):
    """
    Mock STT provider for unit testing and offline development.
    Returns deterministic transcriptions matching language and speech requirements.
    """

    def __init__(self, model_name: str = "mock-stt-v1"):
        self.model = model_name
        self.provider_name = "mock"

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> STTResult:
        # Check for simulated empty audio
        if not audio_bytes or b"EMPTY_SILENCE" in audio_bytes:
            return STTResult(
                text="",
                detected_language=language or "en",
                duration_seconds=0.0,
                provider=self.provider_name,
                model=self.model
            )

        lang = (language or "").strip().lower()
        if lang in ["hi", "hindi", "hi-in"]:
            text = "नमस्ते, मुझे अपने व्यापार के लिए सोशल मीडिया मार्केटिंग और बिलिंग ऑटोमेशन चाहिए।"
            det_lang = "hi"
        elif lang in ["hi-en", "hinglish", "hi_en"]:
            text = "Hello, main apne retail store ke liye WhatsApp automation and social media marketing setup karna chahta hoon."
            det_lang = "hi-en"
        else:
            text = "Hello, I want to set up automated marketing campaigns and lead generation for my business."
            det_lang = "en"

        return STTResult(
            text=text,
            detected_language=det_lang,
            duration_seconds=3.5,
            provider=self.provider_name,
            model=self.model
        )


class GeminiSTTProvider(OpenAIWhisperSTTProvider):
    """
    Backward-compatible alias for Speech-to-Text routing to OpenAI Whisper.
    """
    def __init__(self, model_name: Optional[str] = None):
        super().__init__(model_name=model_name or getattr(settings, "OPENAI_STT_MODEL", "whisper-1"))
        self.provider_name = "openai"


def get_stt_provider(provider_name: Optional[str] = None) -> BaseSTTProvider:
    """
    Factory function resolving the configured Speech-to-Text provider adapter.
    Respects STT_PROVIDER setting ('auto', 'gemini', 'groq', 'openai', 'mock').
    """
    p_name = (provider_name or getattr(settings, "STT_PROVIDER", "auto")).strip().lower()

    if p_name in ["openai", "gemini"]:
        return OpenAIWhisperSTTProvider()
    elif p_name == "groq":
        return GroqWhisperSTTProvider()
    elif p_name == "mock":
        return MockSTTProvider()
    elif p_name == "auto":
        if getattr(settings, "OPENAI_API_KEY", None):
            return OpenAIWhisperSTTProvider()
        elif getattr(settings, "GROQ_API_KEY", None):
            return GroqWhisperSTTProvider()
        elif getattr(settings, "ENVIRONMENT", "").lower() in ["test", "development"]:
            return MockSTTProvider()
        else:
            return OpenAIWhisperSTTProvider() if getattr(settings, "OPENAI_API_KEY", None) else MockSTTProvider()

    raise ValueError(f"Unknown STT provider '{provider_name}'. Supported: 'auto', 'gemini', 'groq', 'openai', 'mock'.")

