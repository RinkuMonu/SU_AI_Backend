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


class GeminiSTTProvider(BaseSTTProvider):
    """
    Speech-to-Text provider using Google Gemini multimodal audio understanding.
    Supports English, Hindi, and mixed Hinglish verbatim transcription.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model = model_name or getattr(settings, "STT_GEMINI_MODEL", "gemini-3-flash-preview")
        self.provider_name = "gemini"

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        **kwargs
    ) -> STTResult:
        from app.ai.gemini_client import get_primary_gemini_client, get_gemini_clients
        from google.genai import types

        clients = get_gemini_clients()
        if not clients:
            raise RuntimeError("Gemini API key is not configured or client failed to initialize.")

        # Normalize clean MIME type (strip parameters like ;codecs=opus)
        clean_mime = mime_type.split(";")[0].strip().lower()
        if clean_mime in ["audio/x-wav", "audio/wave"]:
            clean_mime = "audio/wav"
        elif clean_mime in ["audio/x-m4a", "audio/mp4"]:
            clean_mime = "audio/m4a"

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime)

        lang_instruction = ""
        norm_lang = (language or "").strip().lower()
        if norm_lang in ["hi", "hindi"]:
            lang_instruction = " The audio is spoken in Hindi. Transcribe in Devanagari script."
        elif norm_lang in ["en", "english"]:
            lang_instruction = " The audio is spoken in English."
        elif norm_lang in ["hi-en", "hinglish", "hi_en"]:
            lang_instruction = " The audio is spoken in Hinglish (mixed Hindi and English). Transcribe naturally as spoken."
        elif norm_lang and norm_lang not in ["auto", "auto-detect", "default"]:
            lang_instruction = f" The audio is in '{norm_lang}'."

        system_instruction = (
            "You are a verbatim speech-to-text transcription engine. "
            f"{lang_instruction} "
            "Listen to the audio recording and transcribe exactly what is spoken word-for-word. "
            "Do NOT summarize, do NOT answer questions, do NOT translate, and do NOT add any conversational comments. "
            "If the audio contains Hindi, transcribe in authentic Hindi or Latin script as uttered. "
            "If the audio is Hinglish, transcribe in natural mixed form. "
            "If the recording is completely silent, contains only static noise, or has no discernible human speech, output strictly '[SILENCE]'. "
            "Output ONLY the transcribed words."
        )

        contents = [audio_part, system_instruction]
        if prompt:
            contents.append(f"Contextual vocabulary hint: {prompt}")

        # Attempt transcription across configured Gemini clients
        last_error = None
        for client in clients:
            try:
                # Use client.models.generate_content
                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                )
                raw_text = (response.text or "").strip()
                
                # Check for silence or empty output
                if not raw_text or raw_text in ["[SILENCE]", "EMPTY_AUDIO", "[silence]", ""]:
                    return STTResult(
                        text="",
                        detected_language=norm_lang or "unknown",
                        provider=self.provider_name,
                        model=self.model
                    )

                # Strip possible markdown code wraps if model added them
                if raw_text.startswith("```") and raw_text.endswith("```"):
                    lines = raw_text.splitlines()
                    raw_text = "\n".join(lines[1:-1]).strip()

                # Detect language from text script if not explicitly provided
                detected_lang = norm_lang
                if not detected_lang or detected_lang in ["auto", "auto-detect"]:
                    has_devanagari = any("\u0900" <= ch <= "\u097F" for ch in raw_text)
                    has_latin = any("a" <= ch.lower() <= "z" for ch in raw_text)
                    if has_devanagari and has_latin:
                        detected_lang = "hi-en"
                    elif has_devanagari:
                        detected_lang = "hi"
                    elif has_latin:
                        detected_lang = "en"
                    else:
                        detected_lang = "unknown"

                return STTResult(
                    text=raw_text,
                    detected_language=detected_lang,
                    provider=self.provider_name,
                    model=self.model
                )
            except Exception as e:
                logger.warning(f"Gemini STT attempt failed with client: {e}")
                last_error = e

        raise RuntimeError(f"Gemini speech-to-text failed: {last_error}")


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


def get_stt_provider(provider_name: Optional[str] = None) -> BaseSTTProvider:
    """
    Factory function resolving the configured Speech-to-Text provider adapter.
    Respects STT_PROVIDER setting ('auto', 'gemini', 'groq', 'openai', 'mock').
    """
    p_name = (provider_name or getattr(settings, "STT_PROVIDER", "auto")).strip().lower()

    if p_name == "gemini":
        return GeminiSTTProvider()
    elif p_name == "groq":
        return GroqWhisperSTTProvider()
    elif p_name == "openai":
        return OpenAIWhisperSTTProvider()
    elif p_name == "mock":
        return MockSTTProvider()
    elif p_name == "auto":
        # Auto-selection hierarchy based on configured credentials
        if getattr(settings, "GROQ_API_KEY", None):
            return GroqWhisperSTTProvider()
        elif getattr(settings, "GEMINI_API_KEY", None):
            return GeminiSTTProvider()
        elif getattr(settings, "OPENAI_API_KEY", None):
            return OpenAIWhisperSTTProvider()
        elif getattr(settings, "ENVIRONMENT", "").lower() in ["test", "development"]:
            return MockSTTProvider()
        else:
            # Fallback to GeminiSTTProvider if GEMINI_API_KEY exists else MockSTTProvider
            return GeminiSTTProvider() if getattr(settings, "GEMINI_API_KEY", None) else MockSTTProvider()

    raise ValueError(f"Unknown STT provider '{provider_name}'. Supported: 'auto', 'gemini', 'groq', 'openai', 'mock'.")
