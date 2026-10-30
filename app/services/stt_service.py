import os
import re
import tempfile
import logging
from typing import Optional, Dict, Any, Set
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings
from app.ai.providers.stt_provider import get_stt_provider, STTResult

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS: Set[str] = {
    ".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4", ".flac", ".aac", ".opus"
}

SUPPORTED_MIME_PREFIXES: Set[str] = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/m4a",
    "audio/x-m4a",
    "audio/mp4",
    "audio/flac",
    "audio/x-flac",
    "audio/aac",
    "audio/x-aac",
    "audio/opus",
}

VALID_LANGUAGE_CODES: Set[str] = {
    "en", "eng", "english", "en-in", "en-us", "en-gb",
    "hi", "hin", "hindi", "hi-in",
    "hi-en", "hinglish", "hi_en", "en-hi",
    "auto", "auto-detect", "default"
}


class STTService:
    """
    Speech-to-Text Service for DhandaGrow.
    Provides backend transcription fallback for browsers without native dictation support.
    Accepts audio in English, Hindi, and Hinglish, and returns pure text transcription.
    """

    @classmethod
    def validate_language(cls, language: Optional[str]) -> Optional[str]:
        if not language:
            return None
        clean_lang = language.strip().lower()
        if clean_lang in VALID_LANGUAGE_CODES:
            return clean_lang
        # If user passed custom 2-letter or BCP-47 tag, check format
        if re.match(r"^[a-z]{2,3}(-[a-z0-9]{2,4})?$", clean_lang):
            return clean_lang

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported language '{language}'. "
                "Supported options include English ('en'), Hindi ('hi'), Hinglish ('hi-en'), or automatic detection ('auto')."
            )
        )

    @classmethod
    def detect_and_validate_mime_type(cls, file: UploadFile) -> str:
        raw_mime = (file.content_type or "").split(";")[0].strip().lower()
        filename = (file.filename or "").lower()
        _, ext = os.path.splitext(filename)

        # 1. Match from declared MIME type
        if raw_mime in SUPPORTED_MIME_PREFIXES:
            return raw_mime

        # 2. Match from file extension fallback
        if ext in SUPPORTED_AUDIO_EXTENSIONS:
            ext_map = {
                ".webm": "audio/webm",
                ".wav": "audio/wav",
                ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg",
                ".m4a": "audio/m4a",
                ".mp4": "audio/mp4",
                ".flac": "audio/flac",
                ".aac": "audio/aac",
                ".opus": "audio/opus",
            }
            return ext_map.get(ext, "audio/wav")

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported audio format (content-type: '{raw_mime or 'unknown'}', file: '{filename or 'unknown'}'). "
                "Supported formats: WEBM, WAV, MP3, M4A, OGG, FLAC, AAC."
            )
        )

    @classmethod
    async def transcribe_audio(
        cls,
        file: UploadFile,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        provider_name: Optional[str] = None,
        settings_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Validates, streams, and transcribes user-uploaded audio file securely.
        Guarantees zero persistent storage of user audio files.
        """
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No audio file provided in request."
            )

        # 1. Validate MIME type & file format
        clean_mime = cls.detect_and_validate_mime_type(file)

        # 2. Validate language if supplied
        validated_lang = cls.validate_language(language)

        # 3. Read audio stream with size enforcement
        max_bytes = getattr(settings, "STT_MAX_AUDIO_SIZE_MB", 25) * 1024 * 1024
        chunks = []
        total_size = 0
        chunk_size = 1024 * 512  # 512 KB chunks

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > max_bytes:
                max_mb = getattr(settings, "STT_MAX_AUDIO_SIZE_MB", 25)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Audio file exceeds maximum size limit of {max_mb} MB."
                )
            chunks.append(chunk)

        audio_bytes = b"".join(chunks)

        # 4. Check for empty or near-empty recording
        if len(audio_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio recording is empty (0 bytes). Please upload a valid audio recording."
            )

        # Headers-only audio (e.g. empty wav header < 100 bytes)
        if len(audio_bytes) < 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio recording contains no readable audio data or is too short."
            )

        # 5. Resolve provider adapter
        try:
            stt_provider = get_stt_provider(provider_name)
        except Exception as e:
            logger.error(f"Failed to initialize STT provider: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Speech-to-text service configuration error: {str(e)}"
            )

        # 6. Secure transcription with guaranteed cleanup
        temp_file_path = None
        try:
            # Execute transcription through provider
            result: STTResult = await stt_provider.transcribe(
                audio_bytes=audio_bytes,
                mime_type=clean_mime,
                filename=file.filename or "recording.wav",
                language=validated_lang,
                prompt=prompt,
                **(settings_dict or {})
            )

            # 7. Check for empty or silent transcription
            transcribed_text = (result.text or "").strip()
            if not transcribed_text:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Audio recording was silent, empty, or unclear. No speech could be recognized."
                )

            return {
                "success": True,
                "text": transcribed_text,
                "detected_language": result.detected_language or validated_lang or "auto",
                "processing_status": "completed",
                "provider": result.provider,
                "model": result.model,
                "duration_seconds": result.duration_seconds
            }

        except HTTPException:
            raise
        except TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Speech recognition request timed out. Please try again with a shorter recording."
            )
        except Exception as e:
            err_msg = str(e)
            logger.error(f"STT transcription failure: {err_msg}")
            if "quota" in err_msg.lower() or "429" in err_msg.lower() or "resource_exhausted" in err_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Speech recognition provider quota exceeded or temporarily unavailable. Please retry shortly."
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Speech recognition provider failed: {err_msg[:200]}"
            )
        finally:
            # Guarantee memory and temporary file cleanup
            del audio_bytes
            del chunks
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

