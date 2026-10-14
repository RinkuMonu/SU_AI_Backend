import os
import uuid
import logging
import urllib.parse
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

# Curated, photorealistic, commercial-grade 9:16 vertical product images by category
CURATED_CATEGORY_IMAGES = {
    "laptop": [
        "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=1080&q=85", # Sleek modern aluminum laptop on minimal workspace
        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=1080&q=85", # Premium laptop computer display & keyboard
    ],
    "tech": [
        "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=1080&q=85", # Modern wireless ANC earbuds
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=1080&q=85", # Studio audio headphones
    ],
    "lehenga": [
        "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=1080&q=85", # Royal designer bridal lehenga
        "https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=1080&q=85",
    ],
    "saree": [
        "https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=1080&q=85", # Pure Banarasi Silk Saree
        "https://images.unsplash.com/photo-1617627143750-d86bc21e42bb?w=1080&q=85",
    ],
    "jewelry": [
        "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?w=1080&q=85", # Luxury necklace & jewels
        "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?w=1080&q=85",
    ],
    "beauty": [
        "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=1080&q=85", # Face serum dropper & glowing skin
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=1080&q=85", # Cosmetic skincare bottle
    ],
    "food": [
        "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=1080&q=85", # Gourmet appetizing plating
        "https://images.unsplash.com/photo-1559056199-641a0ac8b55e?w=1080&q=85", # Artisan coffee
    ],
    "streetwear": [
        "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=1080&q=85", # Trendy modern apparel
        "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=1080&q=85", # Streetwear hoodie
    ],
    "general": [
        "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=1080&q=85", # Premium commercial showcase
    ]
}


class ImageGenerator:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations")
        self.api_key = api_key or getattr(settings, "FASHION_IMAGE_API_KEY", None) or getattr(settings, "IMAGE_API_KEY", None)
        self.temp_dir = "uploads/temp"
        os.makedirs(self.temp_dir, exist_ok=True)

    def _detect_category(self, text: str) -> str:
        t = (text or "").lower()
        if any(k in t for k in ["laptop", "macbook", "notebook", "computer", "pc", "desktop", "monitor", "keyboard"]):
            return "laptop"
        if any(k in t for k in ["earbuds", "headphone", "smartwatch", "watch", "tablet", "gadget", "tech", "electronics"]):
            return "tech"
        if any(k in t for k in ["lehenga", "choli", "anarkali", "sherwani", "bridal wear", "ethnic wear"]):
            return "lehenga"
        if any(k in t for k in ["saree", "sari", "banarasi", "silk saree", "kanjivaram", "chanderi", "paithani"]):
            return "saree"
        if any(k in t for k in ["jewelry", "jewellery", "necklace", "earring", "ring", "bangle", "diamond", "polki"]):
            return "jewelry"
        if any(k in t for k in ["serum", "beauty", "skin", "makeup", "glow", "skincare", "cream", "lotion", "cosmetic", "lipstick"]):
            return "beauty"
        if any(k in t for k in ["food", "coffee", "tea", "biryani", "snack", "drink", "beverage", "sweet", "burger", "pizza", "dining"]):
            return "food"
        if any(k in t for k in ["hoodie", "streetwear", "jacket", "tshirt", "t-shirt", "sneaker", "shoes", "jeans", "pants", "clothing", "apparel"]):
            return "streetwear"
        return "general"

    async def _download_and_verify(self, url: str, target_path: str, timeout: float = 15.0) -> bool:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                res = await client.get(url, follow_redirects=True)
                if res.status_code == 200 and len(res.content) > 5000:
                    with open(target_path, "wb") as f:
                        f.write(res.content)
                    return True
        except Exception as e:
            logger.warning(f"Download failed for {url}: {e}")
        return False

    async def generate(
        self,
        prompt: str,
        product_image: str | None = None,
        seed: int = 42,
        scene_idx: int = 0
    ) -> Dict[str, Any]:
        # 1. If explicit product image URL provided, prioritize it
        if product_image and isinstance(product_image, str) and (product_image.startswith("http") or os.path.exists(product_image)):
            return {"image_url": product_image}

        clean_prompt = prompt.replace('\n', ' ').strip()
        category = self._detect_category(clean_prompt)
        curated_list = CURATED_CATEGORY_IMAGES.get(category, CURATED_CATEGORY_IMAGES["general"])
        curated_fallback_url = curated_list[scene_idx % len(curated_list)]

        # 2. Build focused prompt directly matching the specified product
        flux_prompt = (
            f"Editorial commercial product photography of {clean_prompt[:180]}, "
            f"photorealistic, 8k resolution, cinematic commercial lighting, 9:16 vertical orientation, "
            f"advertising studio shoot, crisp details"
        )

        safe_prompt = urllib.parse.quote(flux_prompt[:300])
        pollinations_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=720&height=1280&model=flux&nologo=true&seed={seed + scene_idx}"

        # 3. Attempt download of generated image into local temp file
        local_filename = f"gen_{uuid.uuid4().hex[:12]}.jpg"
        local_path = os.path.join(self.temp_dir, local_filename)

        download_ok = await self._download_and_verify(pollinations_url, local_path, timeout=14.0)
        if download_ok and os.path.exists(local_path):
            return {"image_url": local_path}

        # 4. Fallback to category-matched curated photo (never across categories)
        logger.info(f"Using high-res curated photo for category '{category}': {curated_fallback_url}")
        fallback_local = os.path.join(self.temp_dir, f"curated_{category}_{scene_idx}.jpg")
        if not os.path.exists(fallback_local):
            await self._download_and_verify(curated_fallback_url, fallback_local, timeout=12.0)

        if os.path.exists(fallback_local) and os.path.getsize(fallback_local) > 5000:
            return {"image_url": fallback_local}

        return {"image_url": curated_fallback_url}
