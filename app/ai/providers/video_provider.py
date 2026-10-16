import logging
import asyncio
import uuid
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from app.core.config import settings
from app.ai.providers.veo_provider import (
    VeoVideoProvider,
    VeoError,
    VeoQuotaError,
    VeoModelError
)

logger = logging.getLogger(__name__)

class VideoProvider(ABC):
    @abstractmethod
    async def generate_video(self, image_url: str, prompt: str, duration: int) -> str:
        """Starts video generation and returns a job ID / operation name."""
        pass

    @abstractmethod
    async def get_status(self, job_id: str) -> dict:
        """Returns status of the video generation."""
        pass

    @abstractmethod
    async def get_result(self, job_id: str) -> str:
        """Returns the final video URL."""
        pass


class MockVideoProvider(VideoProvider):
    """
    Mock video provider for development/testing.
    """
    async def generate_video(self, image_url: str, prompt: str, duration: int) -> str:
        logger.info(f"MockVideoProvider: Simulating video generation for prompt={prompt[:50]}...")
        await asyncio.sleep(1)
        return str(uuid.uuid4())

    async def get_status(self, job_id: str) -> dict:
        return {"status": "completed", "progress": 100}

    async def get_result(self, job_id: str) -> str:
        return "https://www.w3schools.com/html/mov_bbb.mp4"


class ExternalVideoProvider(VideoProvider):
    """
    Generic external Video API provider.
    """
    def __init__(self):
        self.api_key = getattr(settings, "VIDEO_API_KEY", None)
        if not self.api_key:
            logger.warning("VIDEO_API_KEY is not configured. Using MockVideoProvider as fallback.")
            self._mock = MockVideoProvider()
        else:
            self._mock = None

    async def generate_video(self, image_url: str, prompt: str, duration: int) -> str:
        if self._mock:
            return await self._mock.generate_video(image_url, prompt, duration)
        return str(uuid.uuid4())

    async def get_status(self, job_id: str) -> dict:
        if self._mock:
            return await self._mock.get_status(job_id)
        return {"status": "completed", "progress": 100}

    async def get_result(self, job_id: str) -> str:
        if self._mock:
            return await self._mock.get_result(job_id)
        return "https://www.w3schools.com/html/mov_bbb.mp4"


def get_video_provider():
    provider_name = getattr(settings, "VIDEO_PROVIDER", "veo").lower()
    if provider_name in ["veo", "gemini"]:
        return VeoVideoProvider()
    elif provider_name == "mock":
        return MockVideoProvider()
    return ExternalVideoProvider()
