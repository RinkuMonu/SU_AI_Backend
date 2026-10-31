import os
import uuid
import logging
import urllib.parse
import httpx
import base64
import io
import re
from typing import Optional, Dict, Any, List
from PIL import Image
from app.core.config import settings

logger = logging.getLogger(__name__)

# Curated, photorealistic, commercial-grade authentic Indian & global images by category
CURATED_CATEGORY_IMAGES = {
    "holi": [
        "/uploads/indian_assets/holi_2.jpg",
        "/uploads/indian_assets/holi_1.jpg",
    ],
    "diwali": [
        "/uploads/indian_assets/diwali_1.jpg",
    ],
    "festive": [
        "/uploads/indian_assets/holi_2.jpg",
        "/uploads/indian_assets/diwali_1.jpg",
        "/uploads/indian_assets/holi_1.jpg",
    ],
    "lehenga": [
        "/uploads/indian_assets/lehenga_1.jpg",
        "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=1080&q=85",
    ],
    "saree": [
        "/uploads/indian_assets/saree_1.jpg",
        "https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=1080&q=85",
    ],
    "jewelry": [
        "/uploads/indian_assets/jewelry_1.jpg",
    ],
    "streetwear": [
        "/uploads/indian_assets/streetwear_1.jpg",
    ],
    "laptop": [
        "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=1080&q=85",
        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=1080&q=85",
    ],
    "tech": [
        "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=1080&q=85",
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=1080&q=85",
    ],
    "beauty": [
        "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=1080&q=85",
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=1080&q=85",
    ],
    "food": [
        "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=1080&q=85",
        "https://images.unsplash.com/photo-1559056199-641a0ac8b55e?w=1080&q=85",
    ],
    "general": [
        "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=1080&q=85",
    ]
}


class ImageGenerator:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations")
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", None)
        self.temp_dir = "uploads/temp"
        os.makedirs(self.temp_dir, exist_ok=True)

    def _detect_category(self, text: str) -> str:
        t = (text or "").lower()
        if any(k in t for k in ["holi", "gulal", "rang", "pichkari"]):
            return "holi"
        if any(k in t for k in ["diwali", "diya", "deepavali", "crackers"]):
            return "diwali"
        if any(k in t for k in ["festiv", "celebrat", "puja", "pooja", "navratri", "eid"]):
            return "festive"
        if any(k in t for k in ["lehenga", "choli", "anarkali", "sherwani", "bridal wear", "ethnic wear", "wedding"]):
            return "lehenga"
        if any(k in t for k in ["saree", "sari", "banarasi", "silk saree", "kanjivaram", "chanderi", "paithani"]):
            return "saree"
        if any(k in t for k in ["jewelry", "jewellery", "necklace", "earring", "ring", "bangle", "diamond", "polki", "gold"]):
            return "jewelry"
        if any(k in t for k in ["laptop", "macbook", "notebook", "computer", "pc", "desktop", "monitor", "keyboard"]):
            return "laptop"
        if any(k in t for k in ["earbuds", "headphone", "smartwatch", "watch", "tablet", "gadget", "tech", "electronics"]):
            return "tech"
        if any(k in t for k in ["serum", "beauty", "skin", "makeup", "glow", "skincare", "cream", "lotion", "cosmetic", "lipstick"]):
            return "beauty"
        if any(k in t for k in ["food", "coffee", "tea", "biryani", "snack", "drink", "beverage", "sweet", "burger", "pizza", "dining"]):
            return "food"
        if any(k in t for k in ["hoodie", "streetwear", "jacket", "tshirt", "t-shirt", "sneaker", "shoes", "jeans", "pants", "clothing", "apparel"]):
            return "streetwear"
        return "general"

    def _crop_watermark_and_save(self, raw_bytes: bytes, target_path: str, target_size: tuple = (1080, 1080)) -> bool:
        """Removes bottom watermark bar and resizes back to target resolution with high quality filter."""
        try:
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            w, h = img.size
            # The watermark is contained within the bottom 48 pixels
            clean_h = max(100, h - 48)
            cropped = img.crop((0, 0, w, clean_h))
            final_img = cropped.resize(target_size, Image.Resampling.LANCZOS)
            final_img.save(target_path, format="JPEG", quality=95)
            return True
        except Exception as e:
            logger.warning(f"Could not crop watermark: {e}")
            try:
                with open(target_path, "wb") as f:
                    f.write(raw_bytes)
                return True
            except Exception:
                return False

    async def _try_openai_image_generation(
        self,
        prompt: str,
        pil_refs: Optional[List[Image.Image]],
        local_path: str
    ) -> Optional[str]:
        """Attempts direct OpenAI image generation using gpt-image-1-mini."""
        if not getattr(settings, "OPENAI_API_KEY", None):
            return None

        try:
            import base64
            from app.ai.providers.openai_provider import OpenAIProvider
            provider = OpenAIProvider()
            logger.info("Attempting OpenAI image generation with gpt-image-1-mini...")
            res = await provider.generate_image(
                prompt=prompt,
                size="1024x1024",
                model=getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
            )

            # Check for base64 image (gpt-image-1-mini primary format)
            b64_data = res.get("b64_json")
            if not b64_data and res.get("images") and isinstance(res["images"], list) and len(res["images"]) > 0:
                b64_data = res["images"][0].get("b64_json")

            if b64_data:
                b64_bytes = base64.b64decode(b64_data)
                if len(b64_bytes) > 500:
                    with open(local_path, "wb") as f:
                        f.write(b64_bytes)
                    logger.info(f"Successfully saved OpenAI base64 image ({len(b64_bytes)} bytes) to {local_path}")
                    return local_path

            # Check for URL image
            img_url = res.get("url") or res.get("image_url")
            if not img_url and res.get("images") and isinstance(res["images"], list) and len(res["images"]) > 0:
                img_url = res["images"][0].get("url")

            if img_url:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(img_url)
                    if r.status_code == 200 and len(r.content) > 1000:
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        logger.info("Successfully generated and saved OpenAI image")
                        return local_path
        except Exception as e:
            logger.warning(f"OpenAI image generation unavailable: {e}")
        return None

    async def generate(
        self,
        prompt: str,
        product_image: str | None = None,
        seed: int = 42,
        scene_idx: int = 0,
        aspect_ratio: str = "1:1",
        pil_refs: Optional[List[Image.Image]] = None
    ) -> Dict[str, Any]:
        # 1. If explicit product image URL provided, prioritize it
        if product_image and isinstance(product_image, str) and (product_image.startswith("http") or os.path.exists(product_image)):
            return {"image_url": product_image}

        clean_prompt = prompt.replace('\n', ' ').strip()
        category = self._detect_category(clean_prompt)
        curated_list = CURATED_CATEGORY_IMAGES.get(category, CURATED_CATEGORY_IMAGES["general"])
        
        # Pick curated index based on seed + scene_idx for diverse regeneration
        chosen_curated = curated_list[(abs(seed) + scene_idx) % len(curated_list)]

        if aspect_ratio == "1:1":
            width, height = 1080, 1080
            orientation_str = "square 1:1 aspect ratio, centered composition"
        elif aspect_ratio == "16:9":
            width, height = 1280, 720
            orientation_str = "16:9 landscape cinematic orientation"
        else:
            width, height = 720, 1280
            orientation_str = "9:16 vertical orientation"

        local_filename = f"gen_{uuid.uuid4().hex[:12]}.jpg"
        local_path = os.path.join(self.temp_dir, local_filename)

        # Check if the prompt is for a brand logo, emblem, or vector icon
        is_logo_scene = any(w in clean_prompt.lower() for w in ["logo", "emblem", "monogram", "brand mark", "vector icon", "brand crest", "minimalist icon"])
        if is_logo_scene:
            return await self.generate_logo(prompt=clean_prompt, seed=seed, width=width, height=height, target_path=local_path)

        # 2. Build strictly photorealistic prompt with authentic Indian ethnicity for human/scene images
        filtered_prompt = re.sub(r'\b(cartoon|anime|illustration|drawing|sketch|painting|vector|3d render|cgi)\b', '', clean_prompt, flags=re.IGNORECASE)

        human_terms = [
            "woman", "women", "girl", "girls", "man", "men", "boy", "boys", "people", "person",
            "model", "face", "portrait", "bride", "groom", "couple", "holi", "diwali", "festiv",
            "celebrat", "saree", "lehenga", "kurta", "sherwani", "ethnic", "fashion"
        ]
        is_human_scene = any(k in filtered_prompt.lower() for k in human_terms)

        if is_human_scene:
            indian_ethnicity_clause = (
                "authentic Indian person with natural South Asian facial features, authentic warm wheatish Indian skin tone, "
                "dark brown eyes, natural black hair, traditional Indian facial structure, candid genuine Indian expression, "
            )
            anti_east_asian = "strictly no Chinese face, no East Asian face, no Caucasian face, no porcelain doll face, no fantasy doll, "
        else:
            indian_ethnicity_clause = ""
            anti_east_asian = ""

        realistic_photo_prompt = (
            f"A real authentic 35mm photograph of {filtered_prompt.strip()}, {indian_ethnicity_clause}"
            f"shot on Canon EOS R5 with 85mm f/1.4 lens, natural lighting, hyper-detailed human skin pores, "
            f"realistic textures, {orientation_str}, 8k resolution, authentic realistic photograph, "
            f"{anti_east_asian}strictly no anime, no cartoon, no 3d render, no illustration, no drawing, no CGI, no painting, no watermark"
        )
        final_prompt = realistic_photo_prompt[:500].strip()

        # 3. Attempt OpenAI Direct Generation
        openai_result_path = await self._try_openai_image_generation(
            prompt=final_prompt,
            pil_refs=pil_refs,
            local_path=local_path
        )
        if openai_result_path and os.path.exists(openai_result_path):
            public_url = settings.get_public_url(f"/uploads/temp/{local_filename}")
            return {"image_url": public_url, "local_path": local_path, "provider": "openai"}

        # 4. For Indian cultural, festive and human categories:
        # Prioritize 100% verified, authentic Indian photography assets to prevent stylized/anime doll outputs
        if category in ["holi", "diwali", "festive", "lehenga", "saree", "jewelry", "streetwear"]:
            if chosen_curated.startswith("/uploads/"):
                public_url = settings.get_public_url(chosen_curated)
                logger.info(f"Delivering authentic Indian photographic asset for '{category}': {public_url}")
                return {"image_url": public_url, "provider": f"authentic-indian-{category}"}
            elif chosen_curated.startswith("http"):
                logger.info(f"Delivering verified curated photographic asset for '{category}': {chosen_curated}")
                return {"image_url": chosen_curated, "provider": f"authentic-indian-{category}"}

        # 5. Non-human / General Fallback via Clean Watermark-Free Pipeline
        safe_prompt = urllib.parse.quote(final_prompt)
        candidate_urls = [
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}",
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width=768&height=768",
            f"https://image.pollinations.ai/prompt/{safe_prompt}",
        ]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
            for render_url in candidate_urls:
                try:
                    res = await client.get(render_url, follow_redirects=True)
                    if res.status_code == 200 and len(res.content) > 5000:
                        cleaned_ok = self._crop_watermark_and_save(res.content, local_path, (width, height))
                        if cleaned_ok and os.path.exists(local_path):
                            public_url = settings.get_public_url(f"/uploads/temp/{local_filename}")
                            logger.info(f"Cleaned watermark-free realistic image saved: {public_url}")
                            return {"image_url": public_url, "local_path": local_path, "provider": "realistic-pipeline"}
                except Exception as e:
                    logger.warning(f"Attempt failed for {render_url}: {e}")
                    continue

        # 6. Absolute Fallback: Curated photo
        if chosen_curated.startswith("/uploads/"):
            return {"image_url": settings.get_public_url(chosen_curated), "provider": "curated-fallback"}
        return {"image_url": chosen_curated, "provider": "curated-fallback"}

    async def generate_logo(
        self,
        prompt: str,
        seed: int = 42,
        width: int = 1024,
        height: int = 1024,
        target_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dedicated, high-quality AI logo generation engine.
        Bypasses photographic human camera clauses and category photo intercepts.
        Produces clean vector, 3D emblem, and brand logo artwork.
        """
        clean_prompt = prompt.replace('\n', ' ').strip()
        local_filename = f"logo_{uuid.uuid4().hex[:12]}.png"
        local_path = target_path or os.path.join(self.temp_dir, local_filename)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # 1. Attempt OpenAI direct generation if configured
        openai_result_path = await self._try_openai_image_generation(
            prompt=clean_prompt,
            pil_refs=None,
            local_path=local_path
        )
        if openai_result_path and os.path.exists(openai_result_path):
            public_url = settings.get_public_url(f"/uploads/brand/{os.path.basename(local_path)}")
            return {"image_url": public_url, "local_path": local_path, "provider": "openai"}

        # 2. Pollinations vector logo pipeline
        safe_prompt = urllib.parse.quote(clean_prompt)
        candidate_urls = [
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}&seed={seed}",
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width=768&height=768&seed={seed}",
            f"https://image.pollinations.ai/prompt/{safe_prompt}?seed={seed}",
        ]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            for render_url in candidate_urls:
                try:
                    res = await client.get(render_url, follow_redirects=True)
                    if res.status_code == 200 and len(res.content) > 3000:
                        # Crop any bottom watermark bar and save crisp PNG
                        cleaned_ok = self._crop_watermark_and_save(res.content, local_path, (width, height))
                        if not cleaned_ok or not os.path.exists(local_path):
                            img = Image.open(io.BytesIO(res.content))
                            img.save(local_path, format="PNG", optimize=True)

                        if os.path.exists(local_path):
                            rel_url = f"/uploads/brand/{os.path.basename(local_path)}"
                            logger.info(f"Generated AI Logo saved to: {local_path}")
                            return {
                                "image_url": rel_url,
                                "local_path": local_path,
                                "provider": "ai-logo-engine"
                            }
                except Exception as e:
                    logger.warning(f"Logo candidate failed for {render_url}: {e}")
                    continue

        # 3. High-Quality Vector Emblem Synthesis Fallback
        try:
            from app.ai.image.logo_designer import generate_artistic_brand_logo
            b_name = "Brand"
            if "'" in clean_prompt:
                b_name = clean_prompt.split("'")[1]
            elif "for " in clean_prompt.lower():
                b_name = clean_prompt.lower().split("for ")[1].split(",")[0].strip().title()

            art_path = generate_artistic_brand_logo(
                business_name=b_name,
                target_path=local_path,
                seed=seed
            )
            rel_url = f"/uploads/brand/{os.path.basename(art_path)}"
            logger.info(f"Generated artistic brand logo fallback saved: {rel_url}")
            return {
                "image_url": rel_url,
                "local_path": art_path,
                "provider": "artistic-logo-designer"
            }
        except Exception as fallback_err:
            logger.error(f"Artistic fallback failed: {fallback_err}")
            raise Exception("AI Logo generation engine timed out or was temporarily unavailable. Please try again.")


