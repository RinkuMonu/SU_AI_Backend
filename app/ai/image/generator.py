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
# Curated, photorealistic, commercial-grade authentic Indian & global images by category
CURATED_CATEGORY_IMAGES = {
    "diwali": [
        "/uploads/indian_assets/diwali_sparklers.jpg",
        "/uploads/indian_assets/diwali_1.jpg",
    ],
    "festive": [
        "/uploads/indian_assets/diwali_sparklers.jpg",
        "/uploads/indian_assets/diwali_1.jpg",
        "/uploads/indian_assets/holi_2.jpg",
        "/uploads/indian_assets/holi_1.jpg",
    ],
    "holi": [
        "/uploads/indian_assets/holi_2.jpg",
        "/uploads/indian_assets/holi_1.jpg",
    ],
    "burger": [
        "/uploads/products/double_smash_burger.jpg",
        "/uploads/food/double_smash_burger.jpg",
        "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=1080&q=85",
    ],
    "food": [
        "/uploads/products/double_smash_burger.jpg",
        "/uploads/food/double_smash_burger.jpg",
        "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=1080&q=85",
        "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=1080&q=85",
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
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=1080&q=85",
        "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=1080&q=85",
    ],
    "beauty": [
        "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=1080&q=85",
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=1080&q=85",
    ],
    "general": [
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=1080&q=85",
    ]
}


class ImageGenerator:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations")
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        self.backup_api_key = getattr(settings, "GEMINI_BACKUP_API_KEY", None)
        self.temp_dir = "uploads/temp"
        os.makedirs(self.temp_dir, exist_ok=True)

    def _detect_category(self, text: str) -> str:
        t = (text or "").lower()
        # 1. Food & Dining (Check first to avoid cross-domain classification)
        if any(k in t for k in [
            "burger", "smash", "patty", "cheddar", "bacon", "pizza", "biryani", "food", "dining",
            "snack", "dish", "cuisine", "restaurant", "cafe", "beverage", "drink", "coffee", "tea",
            "cake", "bakery", "dessert", "sandwich", "fries", "tacos", "pasta", "meal", "delicious",
            "artisanal", "flavor", "crispy", "juicy", "sauce", "bun", "culinary"
        ]):
            return "burger" if any(k in t for k in ["burger", "smash", "patty", "bun"]) else "food"
        
        # 2. Festivals & Celebrations
        if any(k in t for k in ["diwali", "deepavali", "sparkler", "phuljhadi", "diya", "crackers"]):
            return "diwali"
        if any(k in t for k in ["holi", "gulal", "rang", "pichkari"]):
            return "holi"
        if any(k in t for k in ["festiv", "celebrat", "puja", "pooja", "navratri", "eid"]):
            return "festive"
            
        # 3. Fashion & Ethnic Wear
        if any(k in t for k in ["lehenga", "choli", "anarkali", "sherwani", "bridal wear", "ethnic wear", "wedding"]):
            return "lehenga"
        if any(k in t for k in ["saree", "sari", "banarasi", "silk saree", "kanjivaram", "chanderi", "paithani"]):
            return "saree"
        if any(k in t for k in ["jewelry", "jewellery", "necklace", "earring", "ring", "bangle", "diamond", "polki", "gold"]):
            return "jewelry"
        if any(k in t for k in ["hoodie", "streetwear", "jacket", "tshirt", "t-shirt", "sneaker", "shoes", "jeans", "pants", "clothing", "apparel"]):
            return "streetwear"

        # 4. Tech & Electronics
        if any(k in t for k in ["laptop", "macbook", "notebook", "computer", "pc", "desktop", "monitor", "keyboard"]):
            return "laptop"
        if any(k in t for k in ["earbuds", "headphone", "smartwatch", "smart watch", "fitness band", "tablet", "gadget", "charger"]):
            return "tech"
            
        # 5. Beauty & Cosmetics
        if any(k in t for k in ["serum", "beauty", "skin", "makeup", "glow", "skincare", "cream", "lotion", "cosmetic", "lipstick"]):
            return "beauty"
            
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

    async def _try_gemini_image_generation(
        self,
        prompt: str,
        pil_refs: Optional[List[Image.Image]],
        local_path: str
    ) -> Optional[str]:
        """Attempts direct Gemini image generation with multi-key and multi-model support."""
        keys_to_try = [k for k in [self.api_key, self.backup_api_key] if k]
        if not keys_to_try:
            return None

        try:
            import google.genai as genai
            from google.genai import types

            models_to_test = [
                "gemini-2.5-flash-image",
                "gemini-3.1-flash-image",
                "gemini-3.1-flash-lite-image",
                "gemini-3-pro-image"
            ]

            contents = [*pil_refs, prompt] if pil_refs else [prompt]
            config = types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

            for key in keys_to_try:
                try:
                    client = genai.Client(api_key=key)
                    for model_name in models_to_test:
                        try:
                            logger.info(f"Attempting Gemini image generation with model {model_name}...")
                            res = client.models.generate_content(
                                model=model_name,
                                contents=contents,
                                config=config
                            )
                            if res and res.candidates:
                                for cand in res.candidates:
                                    if cand.content and cand.content.parts:
                                        for part in cand.content.parts:
                                            if hasattr(part, "as_image"):
                                                img = part.as_image()
                                                if img:
                                                    img.save(local_path, format="JPEG", quality=95)
                                                    logger.info(f"Successfully generated image via Gemini ({model_name})")
                                                    return local_path
                                            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                                                raw_data = part.inline_data.data
                                                if isinstance(raw_data, str):
                                                    raw_data = base64.b64decode(raw_data)
                                                with open(local_path, "wb") as f:
                                                    f.write(raw_data)
                                                logger.info(f"Successfully saved Gemini inline image ({model_name})")
                                                return local_path
                        except Exception as model_err:
                            err_msg = str(model_err)
                            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "402" in err_msg:
                                break
                            continue
                except Exception as key_err:
                    logger.debug(f"Gemini key attempt error: {key_err}")
                    continue
        except Exception as e:
            logger.warning(f"Gemini image generation unavailable: {e}")
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

        # 2. Build strictly photorealistic prompt with authentic Indian ethnicity
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
            texture_detail = "hyper-detailed human skin pores, "
        else:
            indian_ethnicity_clause = ""
            anti_east_asian = ""
            texture_detail = "rich savory details, authentic gourmet texture, "

        realistic_photo_prompt = (
            f"A real authentic 35mm photograph of {filtered_prompt.strip()}, {indian_ethnicity_clause}"
            f"shot on Canon EOS R5 with 85mm f/1.4 lens, natural lighting, {texture_detail}"
            f"realistic textures, {orientation_str}, 8k resolution, authentic realistic photograph, "
            f"{anti_east_asian}strictly no anime, no cartoon, no 3d render, no illustration, no drawing, no CGI, no painting, no watermark"
        )
        final_prompt = realistic_photo_prompt[:500].strip()

        # 3. Attempt Gemini Direct Generation
        gemini_result_path = await self._try_gemini_image_generation(
            prompt=final_prompt,
            pil_refs=pil_refs,
            local_path=local_path
        )
        if gemini_result_path and os.path.exists(gemini_result_path):
            public_url = settings.get_public_url(f"/uploads/temp/{local_filename}")
            return {"image_url": public_url, "local_path": local_path, "provider": "gemini"}

        # 4. For Indian cultural, festive, food, and human categories:
        # Prioritize 100% verified, authentic photography assets to prevent stylized/anime or mismatched outputs
        if category in ["holi", "diwali", "festive", "lehenga", "saree", "jewelry", "streetwear", "burger", "food"]:
            clean_curated = chosen_curated.lstrip("/\\")
            if os.path.exists(clean_curated) and os.path.getsize(clean_curated) > 5000:
                public_url = settings.get_public_url(f"/{clean_curated.replace(os.sep, '/')}")
                logger.info(f"Delivering authentic local photographic asset for '{category}': {public_url}")
                return {"image_url": public_url, "local_path": clean_curated, "provider": f"authentic-{category}"}
            if chosen_curated.startswith("/uploads/"):
                public_url = settings.get_public_url(chosen_curated)
                logger.info(f"Delivering authentic photographic asset for '{category}': {public_url}")
                return {"image_url": public_url, "provider": f"authentic-{category}"}
            elif chosen_curated.startswith("http"):
                logger.info(f"Delivering verified curated photographic asset for '{category}': {chosen_curated}")
                return {"image_url": chosen_curated, "provider": f"authentic-{category}"}

        # 5. Non-human / General Fallback via Clean Watermark-Free Pipeline
        safe_prompt = urllib.parse.quote(final_prompt)
        candidate_urls = [
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width=768&height=768",
            f"https://image.pollinations.ai/prompt/{safe_prompt}?width={width}&height={height}&model=flux",
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


