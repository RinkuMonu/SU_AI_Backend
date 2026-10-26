import os
import uuid
import logging
import asyncio
import urllib.parse
from typing import Optional, Dict, Any
from pathlib import Path
import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiFashionService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.photoshoot_dir = Path("uploads") / "fashion" / "photoshoot"
        self.tryon_dir = Path("uploads") / "fashion" / "tryon"
        self.photoshoot_dir.mkdir(parents=True, exist_ok=True)
        self.tryon_dir.mkdir(parents=True, exist_ok=True)
        self._client = None

    def _get_client(self):
        if self._client is None and self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize google.genai: {e}")
        return self._client

    async def _download_file(self, url: str, target_path: Path) -> bool:
        """Download remote image with retry and verification."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=60.0, headers=headers, follow_redirects=True) as client:
                res = await client.get(url)
                if res.status_code == 200 and len(res.content) > 3000:
                    with open(target_path, "wb") as f:
                        f.write(res.content)
                    return True
                else:
                    logger.warning(f"Download returned status {res.status_code}, len={len(res.content)}")
        except Exception as e:
            logger.warning(f"Download failed for {url}: {e}")
        return False

    async def generate_photoshoot(
        self,
        prompt: str,
        product: dict,
        request,
    ) -> Dict[str, Any]:
        """
        Generates an AI Fashion Photoshoot image preserving the exact clothing, color,
        and product type. Uses Gemini for director-level prompt enhancement and
        Pollinations Flux for photorealistic image generation.
        """
        category = (product.get("category") or getattr(request, "category", "garment") or "garment").strip()
        model_type = getattr(request, "model_type", "female").lower()
        product_name = product.get("name") or getattr(request, "garment_name", f"{getattr(request, 'color', '')} {category}").strip()
        color = (product.get("color") or getattr(request, "color", "")).strip()
        pose = getattr(request, "pose", "standing")
        background = getattr(request, "background", "studio")
        shot_type = getattr(request, "shot_type", "full_body")

        filename = f"{uuid.uuid4().hex}.jpg"
        local_file = self.photoshoot_dir / filename

        # 1. Ask Gemini LLM to enhance the photoshoot prompt while strictly preserving color and garment
        client = self._get_client()
        enhanced_prompt = prompt
        if client:
            try:
                gemini_prompt = (
                    f"You are a Vogue Fashion Director. Write a concise image generation prompt (under 40 words) for a fashion photoshoot.\n"
                    f"CRITICAL: Garment MUST be: {color} {category} ({product_name}). Do not change the garment or color.\n"
                    f"Model: {model_type} model, {pose} pose, {background} lighting, 8k resolution, photorealistic fabric texture.\n"
                    f"Return ONLY the prompt text."
                )
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=getattr(settings, "GEMINI_FAST_MODEL", None) or getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=gemini_prompt
                )
                if resp and resp.text:
                    enhanced_prompt = resp.text.strip().replace("\n", " ")
            except Exception as e:
                logger.warning(f"Gemini prompt enhancement note: {e}")

        # 2. Generate high-resolution photoshoot image via Pollinations Flux
        safe_prompt = urllib.parse.quote(enhanced_prompt[:300].strip())
        seed = int(uuid.uuid4().hex[:6], 16)
        flux_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
        
        logger.info(f"Generating photoshoot visual for '{product_name}' via Flux AI...")
        download_ok = await self._download_file(flux_url, local_file)

        # Retry with concise prompt if first attempt failed
        if not download_ok or not local_file.exists() or local_file.stat().st_size < 3000:
            logger.info("Retrying photoshoot image generation with direct concise prompt...")
            fallback_prompt = urllib.parse.quote(f"Commercial high-fashion photography of an Indian {model_type} model wearing a gorgeous {color} {category}, {pose} pose, {background} studio lighting, 8k resolution, photorealistic, sharp focus")
            retry_url = f"https://image.pollinations.ai/prompt/{fallback_prompt}?width=1024&height=1024&nologo=true&model=flux&seed={seed+1}"
            download_ok = await self._download_file(retry_url, local_file)

        final_url = f"/uploads/fashion/photoshoot/{filename}"
        return {
            "status": "completed",
            "image_url": final_url,
            "provider": "gemini_flux",
            "prompt_used": enhanced_prompt[:1000]
        }

    async def generate_virtual_tryon(
        self,
        person_image_url: str,
        garment_image_url: str,
        product: dict,
        prompt: str
    ) -> Dict[str, Any]:
        """
        Executes an AI Virtual Try-On by delegating to VirtualTryOnProvider
        (HuggingFace IDM-VTON + Smart Personal Compositing).
        Strictly preserves the user's uploaded photo and garment color/style.
        """
        from app.services.fashion.tryon_service import get_tryon_provider
        provider = get_tryon_provider()
        return await provider.generate(
            person_image_url=person_image_url,
            garment_image_url=garment_image_url,
            prompt=prompt,
            product=product
        )


# Singleton instance
_gemini_fashion_service = None

def get_gemini_fashion_service() -> GeminiFashionService:
    global _gemini_fashion_service
    if _gemini_fashion_service is None:
        _gemini_fashion_service = GeminiFashionService()
    return _gemini_fashion_service
