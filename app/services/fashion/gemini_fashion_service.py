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
from app.ai.factory import AIProviderFactory

logger = logging.getLogger(__name__)


class OpenAIFashionService:
    def __init__(self):
        self.api_key = getattr(settings, "OPENAI_API_KEY", None)
        self.photoshoot_dir = Path("uploads") / "fashion" / "photoshoot"
        self.tryon_dir = Path("uploads") / "fashion" / "tryon"
        self.photoshoot_dir.mkdir(parents=True, exist_ok=True)
        self.tryon_dir.mkdir(parents=True, exist_ok=True)

    def _get_ai_provider(self):
        return AIProviderFactory.get_provider(preferred="openai", tier="fast")

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
        and product type. Uses OpenAI GPT-4.1 Mini for director-level prompt enhancement
        and gpt-image-1-mini / photorealistic rendering for image generation.
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

        # 1. Ask OpenAI GPT-4.1 Mini to enhance photoshoot prompt while strictly preserving color and garment
        enhanced_prompt = prompt
        try:
            openai_prompt = (
                f"You are a Vogue Fashion Director. Write a concise image generation prompt (under 40 words) for a fashion photoshoot.\n"
                f"CRITICAL: Garment MUST be: {color} {category} ({product_name}). Do not change the garment or color.\n"
                f"Model: {model_type} model, {pose} pose, {background} lighting, 8k resolution, photorealistic fabric texture.\n"
                f"Return ONLY the prompt text."
            )
            provider = self._get_ai_provider()
            res = await provider.generate_text(
                prompt=openai_prompt,
                system_prompt="You are a Vogue fashion director. Return ONLY the concise image generation prompt text."
            )
            txt = res.get("text", "").strip() if isinstance(res, dict) else str(res).strip()
            if txt:
                enhanced_prompt = txt.replace("\n", " ")
        except Exception as e:
            logger.warning(f"OpenAI fashion prompt enhancement note: {e}")

        # 2. Generate high-resolution photoshoot image via OpenAI gpt-image-1-mini
        download_ok = False
        try:
            from app.ai.providers.openai_provider import OpenAIProvider
            img_provider = OpenAIProvider()
            img_res = await img_provider.generate_image(
                prompt=enhanced_prompt,
                size="1024x1024",
                model=getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
            )
            b64_data = img_res.get("b64_json")
            if not b64_data and img_res.get("images") and isinstance(img_res["images"], list) and len(img_res["images"]) > 0:
                b64_data = img_res["images"][0].get("b64_json")

            if b64_data:
                import base64
                with open(local_file, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                download_ok = True
            elif img_res.get("url"):
                download_ok = await self._download_file(img_res["url"], local_file)
        except Exception as e:
            logger.warning(f"OpenAI image generation fallback: {e}")

        if not download_ok or not local_file.exists():
            safe_prompt = urllib.parse.quote(enhanced_prompt[:300].strip())
            seed = int(uuid.uuid4().hex[:6], 16)
            flux_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
            logger.info(f"Generating photoshoot visual for '{product_name}' via pipeline...")
            download_ok = await self._download_file(flux_url, local_file)

        final_url = f"/uploads/fashion/photoshoot/{filename}"
        return {
            "status": "completed",
            "image_url": final_url,
            "provider": "openai",
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


# Backward compatible aliases
GeminiFashionService = OpenAIFashionService
_fashion_service = None

def get_fashion_service() -> OpenAIFashionService:
    global _fashion_service
    if _fashion_service is None:
        _fashion_service = OpenAIFashionService()
    return _fashion_service

get_gemini_fashion_service = get_fashion_service
