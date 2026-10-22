import os
import uuid
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class VoiceProvider(ABC):
    @abstractmethod
    async def generate_audio(self, text: str, language: str = "Hinglish", voice: Optional[str] = None, speed: float = 1.0) -> str:
        pass


class MockVoiceProvider(VoiceProvider):
    """
    A mock voice provider that simulates TTS generation.
    Returns a placeholder audio URL without requiring any local tools.
    Replace this with a real API-based TTS provider (ElevenLabs, Google TTS, Azure TTS, etc.)
    when you have the credentials.
    """
    async def generate_audio(self, text: str, language: str = "Hinglish", voice: Optional[str] = None, speed: float = 1.0) -> str:
        logger.info(f"MockVoiceProvider: Simulating TTS for language={language}, voice={voice}")
        # Simulate a small delay like a real API call
        await asyncio.sleep(0.5)
        output_dir = "uploads/audio"
        os.makedirs(output_dir, exist_ok=True)
        # Return a placeholder audio URL
        fake_filename = f"{uuid.uuid4()}.mp3"
        return f"/uploads/audio/{fake_filename}"


class PiperVoiceProvider(VoiceProvider):
    """
    Piper TTS provider - requires piper binary and voice models installed locally.
    NOTE: This does NOT work on Windows due to asyncio subprocess limitations.
    Use MockVoiceProvider or an API-based provider instead.
    """
    def __init__(self):
        self.piper_path = getattr(settings, "PIPER_PATH", "piper")
        self.voices_dir = getattr(settings, "PIPER_VOICES_DIR", "./piper_voices")
        self.output_dir = "uploads/audio"
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_audio(self, text: str, language: str = "Hinglish", voice: Optional[str] = None, speed: float = 1.0) -> str:
        filename = f"{uuid.uuid4()}.wav"
        output_path = os.path.join(self.output_dir, filename)

        voice_model_path = os.path.join(self.voices_dir, f"{voice}.onnx") if voice else None
        if not voice_model_path or not os.path.exists(voice_model_path):
            logger.warning(f"Piper voice model {voice_model_path} not found. Falling back to GTTS/mock.")
            try:
                gtts = GTTSVoiceProvider()
                return await gtts.generate_audio(text=text, language=language, voice=voice, speed=speed)
            except Exception:
                mock = MockVoiceProvider()
                return await mock.generate_audio(text=text, language=language, voice=voice, speed=speed)

        command = f'echo "{text}" | {self.piper_path} --model {voice_model_path} --output_file {output_path}'

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Piper error: {stderr.decode()}")
                raise Exception("Voice generation failed.")

            return f"/uploads/audio/{filename}"

        except NotImplementedError:
            logger.warning("asyncio subprocess not supported on this platform. Using MockVoiceProvider.")
            mock = MockVoiceProvider()
            return await mock.generate_audio(text=text, language=language, voice=voice, speed=speed)
        except Exception as e:
            logger.error(f"Error in PiperVoiceProvider: {str(e)}")
            raise e


class GTTSVoiceProvider(VoiceProvider):
    """
    gTTS (Google Text-to-Speech) provider fallback.
    Generates an mp3 file locally.
    """
    def __init__(self):
        self.output_dir = "uploads/audio"
        os.makedirs(self.output_dir, exist_ok=True)
        
    async def generate_audio(self, text: str, language: str = "Hinglish", voice: Optional[str] = None, speed: float = 1.0) -> str:
        logger.info(f"GTTSVoiceProvider: Generating audio for language={language}")
        
        # For Hinglish in Latin script, 'en' with Indian accent works better in gTTS than 'hi' which expects Devanagari
        lang_code = "en"
        tld = "co.in"
        if language and language.lower() == "hindi":
            lang_code = "hi"
            tld = "com"
            
        filename = f"{uuid.uuid4()}.mp3"
        output_path = os.path.join(self.output_dir, filename)
        
        def _generate():
            from gtts import gTTS
            tts = gTTS(text=text, lang=lang_code, tld=tld, slow=(speed < 1.0))
            tts.save(output_path)
            
        try:
            await asyncio.to_thread(_generate)
            return f"/uploads/audio/{filename}"
        except Exception as e:
            logger.warning(f"GTTS generation failed: {e}. Falling back to mock voice.")
            mock = MockVoiceProvider()
            return await mock.generate_audio(text=text, language=language, voice=voice, speed=speed)


class EdgeTTSVoiceProvider(VoiceProvider):
    """
    Microsoft Edge Neural TTS Provider.
    Generates ultra-realistic, natural human voices for Instagram Reels in Hinglish, Hindi, and English.
    """
    def __init__(self):
        self.output_dir = "uploads/audio"
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_audio(self, text: str, language: str = "Hinglish", voice: Optional[str] = None, speed: float = 1.0) -> str:
        lang_str = (language or "").lower()

        # Natural neural voices: Swara is the gold standard for Hinglish & Hindi creator reels
        if "hinglish" in lang_str:
            selected_voice = "hi-IN-SwaraNeural"
        elif "hindi" in lang_str:
            selected_voice = "hi-IN-SwaraNeural"
        elif "english" in lang_str:
            selected_voice = "en-IN-NeerjaNeural"
        else:
            selected_voice = "en-IN-NeerjaNeural"

        # Explicit override if given
        if voice and ("Neural" in voice or "en-" in voice or "hi-" in voice):
            selected_voice = voice

        # Speed / rate tuning
        rate_str = "+0%"
        if speed > 1.0:
            rate_pct = int((speed - 1.0) * 100)
            rate_str = f"+{rate_pct}%"
        elif speed < 1.0:
            rate_pct = int((1.0 - speed) * 100)
            rate_str = f"-{rate_pct}%"

        filename = f"{uuid.uuid4()}.mp3"
        output_path = os.path.join(self.output_dir, filename)

        try:
            import edge_tts
            communicate = edge_tts.Communicate(text=text, voice=selected_voice, rate=rate_str)
            await communicate.save(output_path)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"EdgeTTS generated audio successfully: {output_path} (voice={selected_voice})")
                return f"/uploads/audio/{filename}"
        except Exception as e:
            logger.warning(f"EdgeTTS generation failed: {e}. Falling back to GTTS...")

        # Fallback to gTTS if edge-tts encounters any issue
        try:
            gtts = GTTSVoiceProvider()
            return await gtts.generate_audio(text=text, language=language, voice=voice, speed=speed)
        except Exception:
            mock = MockVoiceProvider()
            return await mock.generate_audio(text=text, language=language, voice=voice, speed=speed)


def get_voice_provider() -> VoiceProvider:
    provider_name = getattr(settings, "VOICE_PROVIDER", "gtts").lower()
    if provider_name == "piper":
        return PiperVoiceProvider()
    elif provider_name == "mock":
        return MockVoiceProvider()
    elif provider_name == "gtts":
        return GTTSVoiceProvider()
    elif provider_name == "edge-tts":
        try:
            import edge_tts
            return EdgeTTSVoiceProvider()
        except ImportError:
            return GTTSVoiceProvider()
    else:
        # Default to GTTS fallback
        return GTTSVoiceProvider()
