import io
import wave
import pytest
from unittest.mock import patch, MagicMock
from bson import ObjectId
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.services.stt_service import STTService
from app.ai.providers.stt_provider import STTResult, MockSTTProvider

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    # Ensure STT uses mock provider during automated test suite runs
    prev_stt_provider = settings.STT_PROVIDER
    settings.STT_PROVIDER = "mock"
    yield
    settings.STT_PROVIDER = prev_stt_provider
    close_mongo_connection()

async def create_auth_user(db, name: str = "Voice User"):
    user_id = ObjectId()
    email = f"voice_{user_id}@dhandagrow.test"
    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": f"+919{str(user_id)[-9:]}",
        "hashed_password": get_password_hash("TestPass@123"),
        "role": "businessman",
        "email_verified": True,
        "phone_verified": True,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(user_doc)
    token = create_access_token(subject=str(user_id))
    return str(user_id), token

def generate_dummy_wav(duration_sec: float = 0.5, num_channels: int = 1, sample_rate: int = 16000) -> bytes:
    """Generates a valid minimal WAV audio binary."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Synthetic sine-like non-silent frames
        samples = int(duration_sec * sample_rate)
        frames = b"\x10\x20\x30\x40" * (samples // 2)
        wf.writeframes(frames)
    return buf.getvalue()


# 1. English Speech Transcription
async def test_transcribe_english_audio_success():
    db = get_database()
    uid, token = await create_auth_user(db, name="Amit Roy")
    wav_bytes = generate_dummy_wav(1.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("recording.wav", wav_bytes, "audio/wav")}
        data = {"language": "en"}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files, data=data)
        assert res.status_code == 200
        res_data = res.json()
        assert res_data["success"] is True
        assert "text" in res_data
        assert len(res_data["text"]) > 0
        assert res_data["detected_language"] == "en"
        assert res_data["processing_status"] == "completed"
        assert res_data["provider"] == "mock"


# 2. Hindi Speech Transcription
async def test_transcribe_hindi_audio_success():
    db = get_database()
    uid, token = await create_auth_user(db, name="Sunita Devi")
    wav_bytes = generate_dummy_wav(1.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("voice_note.webm", wav_bytes, "audio/webm")}
        data = {"language": "hi"}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files, data=data)
        assert res.status_code == 200
        res_data = res.json()
        assert res_data["success"] is True
        assert res_data["detected_language"] == "hi"
        assert "व्यापार" in res_data["text"] or "नमस्ते" in res_data["text"]


# 3. Hinglish (Mixed Hindi-English) Speech Transcription
async def test_transcribe_hinglish_audio_success():
    db = get_database()
    uid, token = await create_auth_user(db, name="Rahul Verma")
    wav_bytes = generate_dummy_wav(1.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("dictation.m4a", wav_bytes, "audio/m4a")}
        data = {"language": "hi-en"}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files, data=data)
        assert res.status_code == 200
        res_data = res.json()
        assert res_data["success"] is True
        assert res_data["detected_language"] == "hi-en"
        assert "automation" in res_data["text"].lower() or "store" in res_data["text"].lower()


# 4. Invalid Audio Format Rejection
async def test_transcribe_unsupported_audio_format():
    db = get_database()
    uid, token = await create_auth_user(db)
    text_bytes = b"This is plain text, not an audio file."

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("document.txt", text_bytes, "text/plain")}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
        assert res.status_code == 400
        assert "Unsupported audio format" in res.json()["detail"]


# 5. Empty Audio File Rejection
async def test_transcribe_empty_audio_file():
    db = get_database()
    uid, token = await create_auth_user(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("empty.wav", b"", "audio/wav")}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
        assert res.status_code == 400
        assert "empty" in res.json()["detail"].lower()


# 6. Unclear / Silent Recording Handling
async def test_transcribe_silent_recording_returns_meaningful_error():
    db = get_database()
    uid, token = await create_auth_user(db)
    # Simulated silence token recognized by mock provider
    silent_audio = generate_dummy_wav(0.5) + b"EMPTY_SILENCE"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("silence.wav", silent_audio, "audio/wav")}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
        assert res.status_code == 400
        assert "silent" in res.json()["detail"].lower() or "unclear" in res.json()["detail"].lower()


# 7. Large Audio File Rejection (> 25 MB)
async def test_transcribe_large_audio_rejected():
    db = get_database()
    uid, token = await create_auth_user(db)

    # Mock chunk reader to simulate a stream exceeding 25 MB without allocating 26 MB RAM in tests
    with patch.object(settings, "STT_MAX_AUDIO_SIZE_MB", 1):  # Set limit to 1 MB for testing
        large_bytes = b"A" * (1024 * 1024 + 100)  # > 1 MB

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"Authorization": f"Bearer {token}"}
            files = {"file": ("large_voice.wav", large_bytes, "audio/wav")}

            res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
            assert res.status_code == 413
            assert "exceeds maximum size" in res.json()["detail"].lower()


# 8. Unsupported Language Validation
async def test_transcribe_unsupported_language_code():
    db = get_database()
    uid, token = await create_auth_user(db)
    wav_bytes = generate_dummy_wav(0.5)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("recording.wav", wav_bytes, "audio/wav")}
        data = {"language": "invalid-unsupported-lang-xyz-123"}

        res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files, data=data)
        assert res.status_code == 400
        assert "Unsupported language" in res.json()["detail"]


# 9. Authentication Required
async def test_transcribe_requires_authentication():
    wav_bytes = generate_dummy_wav(0.5)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        files = {"file": ("recording.wav", wav_bytes, "audio/wav")}
        res = await ac.post("/api/v1/ai/speech-to-text", files=files)
        # 401 Unauthorized when missing token
        assert res.status_code == 401


# 10. Provider Failure Handling (502 Bad Gateway)
async def test_transcribe_provider_failure_returns_502():
    db = get_database()
    uid, token = await create_auth_user(db)
    wav_bytes = generate_dummy_wav(0.5)

    with patch.object(MockSTTProvider, "transcribe", side_effect=RuntimeError("External STT Gateway 503 Service Unavailable")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"Authorization": f"Bearer {token}"}
            files = {"file": ("recording.wav", wav_bytes, "audio/wav")}

            res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
            assert res.status_code == 502
            assert "Speech recognition provider failed" in res.json()["detail"]


# 11. Provider Quota Limit Handling
async def test_transcribe_provider_quota_returns_502_with_clear_message():
    db = get_database()
    uid, token = await create_auth_user(db)
    wav_bytes = generate_dummy_wav(0.5)

    with patch.object(MockSTTProvider, "transcribe", side_effect=Exception("429 ResourceExhausted: Quota exceeded")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"Authorization": f"Bearer {token}"}
            files = {"file": ("recording.wav", wav_bytes, "audio/wav")}

            res = await ac.post("/api/v1/ai/speech-to-text", headers=headers, files=files)
            assert res.status_code == 502
            assert "quota" in res.json()["detail"].lower()

