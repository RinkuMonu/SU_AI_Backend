"""
Fashion AI Photoshoot Service
Handles async fashion image generation with status tracking.
"""
from datetime import datetime, timezone
from typing import Optional
import urllib.parse
import logging

from bson import ObjectId

from app.services.fashion.prompt_service import (
    build_fashion_photoshoot_prompt,
    build_fashion_negative_prompt,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------
# Image Generation Provider Abstraction
# ----------------------------------------------

class FashionImageProvider:
    """
    Pluggable image generation provider for Fashion AI.
    Uses Google Gemini API as primary provider.
    """

    def __init__(self, provider_name: str = "openai"):
        self.provider_name = provider_name

    async def generate(self, prompt: str, product: dict = None, request = None, **kwargs) -> dict:
        """
        Generate a fashion image from a prompt using Gemini.
        Returns: {"status": "completed", "image_url": "...", "provider": "openai"}
        """
        from app.services.fashion.gemini_fashion_service import get_gemini_fashion_service
        return await get_gemini_fashion_service().generate_photoshoot(
            prompt=prompt,
            product=product or {},
            request=request
        )


# Singleton instance
_image_provider: Optional[FashionImageProvider] = None


def get_fashion_image_provider() -> FashionImageProvider:
    global _image_provider
    if _image_provider is None:
        _image_provider = FashionImageProvider(provider_name="openai")
    return _image_provider


# ----------------------------------------------
# Core Photoshoot Service
# ----------------------------------------------

async def create_fashion_generation_job(
    db,
    user_id: str,
    product: dict,
    request,
) -> str:
    """
    Creates a pending fashion_generation document in MongoDB.
    Returns the generation_id (string).
    """
    now = datetime.now(timezone.utc)
    p_name = product.get("name") or getattr(request, "garment_name", None) or f"{request.color} {request.category}"
    doc = {
        "user_id": user_id,
        "product_id": str(product.get("id") or product.get("_id", "")),
        "product_name": p_name,
        "type": "photoshoot",
        "model_type": request.model_type,
        "model_style": request.model_style,
        "pose": request.pose,
        "background": request.background,
        "location": request.location,
        "shot_type": request.shot_type,
        "view": request.view,
        "status": "pending",
        "result_images": [],
        "provider": "openai",
        "provider_job_id": None,
        "prompt_used": None,
        "error": None,
        "created_at": now,
        "completed_at": None,
    }
    result = await db["fashion_generations"].insert_one(doc)
    return str(result.inserted_id)


async def run_fashion_photoshoot(
    db,
    generation_id: str,
    user_id: str,
    product: dict,
    request,
    text_generator=None,
) -> None:
    """
    Background task: generate fashion photoshoot image and update DB.
    This runs asynchronously after the HTTP response is sent.
    """
    collection = db["fashion_generations"]

    async def update_status(status: str, **kwargs):
        await collection.update_one(
            {"_id": ObjectId(generation_id)},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc), **kwargs}}
        )

    try:
        # Mark as processing
        await update_status("processing")

        # 1. Build structured prompt
        base_prompt = build_fashion_photoshoot_prompt(
            product_name=product.get("name", "garment"),
            category=product.get("category", "clothing"),
            color=product.get("color", ""),
            gender=product.get("gender", "unisex"),
            model_type=request.model_type,
            model_style=request.model_style,
            pose=request.pose,
            background=request.background,
            location=request.location,
            shot_type=request.shot_type,
            view=request.view,
            custom_pose_description=getattr(request, "custom_pose_description", None),
            custom_background_description=getattr(request, "custom_background_description", None),
        )

        # 2. Optionally enhance with Groq LLM
        final_prompt = base_prompt
        if text_generator:
            try:
                llm_prompt = f"""You are a professional fashion photography prompt engineer.
Enhance the following prompt for Stable Diffusion / Flux image generation.
Keep all specific garment details EXACTLY as described. Only add photographic quality descriptors.
Return ONLY the enhanced prompt text, nothing else.

Original prompt:
{base_prompt}"""
                response = await text_generator.generate_text(prompt=llm_prompt, max_tokens=600)
                enhanced = response.get("text", "").strip()
                if enhanced and len(enhanced) > 50:
                    final_prompt = enhanced
            except Exception as e:
                logger.warning(f"Groq prompt enhancement failed, using base prompt: {e}")

        negative_prompt = build_fashion_negative_prompt()

        # 3. Generate image
        provider = get_fashion_image_provider()
        result = await provider.generate(prompt=final_prompt, product=product, request=request)

        if result.get("status") == "failed":
            await update_status(
                "failed",
                error=result.get("error", "Image generation failed"),
                completed_at=datetime.now(timezone.utc),
            )
            return

        image_url = result["image_url"]

        # 4. Update generation record as completed
        await update_status(
            "completed",
            result_images=[image_url],
            provider=result.get("provider", "openai"),
            prompt_used=final_prompt[:1000],
            completed_at=datetime.now(timezone.utc),
        )

        # 5. Also save to shared contents library for cross-module use
        try:
            await db["contents"].insert_one({
                "user_id": user_id,
                "type": "fashion_photoshoot",
                "source_id": generation_id,
                "product_id": str(product.get("id") or ""),
                "title": f"Fashion Photoshoot - {product.get('name', 'Product')}",
                "media_url": image_url,
                "status": "generated",
                "created_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning(f"Could not save to contents library: {e}")

    except Exception as e:
        logger.error(f"Fashion photoshoot generation failed: {e}")
        await update_status(
            "failed",
            error=str(e),
            completed_at=datetime.now(timezone.utc),
        )
