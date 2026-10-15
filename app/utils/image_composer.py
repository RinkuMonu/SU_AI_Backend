import io
import os
import uuid
import logging
import httpx
from PIL import Image, ImageDraw, ImageFont
from app.core.config import settings

logger = logging.getLogger(__name__)


class ImageComposer:
    
    @staticmethod
    async def generate_banner(
        product_image_url: str,
        headline: str,
        cta: str,
        brand_colors: dict = None,
    ) -> str:
        brand_colors = brand_colors or {}
        try:
            product_img = None
            save_dir = os.path.join(os.getcwd(), "uploads")
            os.makedirs(save_dir, exist_ok=True)

            # 1. Resolve product image (Local disk first, then remote HTTP)
            clean_url = (product_image_url or "").strip()
            if "uploads/" in clean_url:
                local_filename = clean_url.split("uploads/")[-1].split("?")[0]
                local_path = os.path.join(save_dir, local_filename)
                if os.path.exists(local_path):
                    try:
                        product_img = Image.open(local_path).convert("RGBA")
                    except Exception as e:
                        logger.warning(f"Failed to open local image {local_path}: {e}")

            if not product_img and clean_url.startswith("http"):
                try:
                    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                        response = await client.get(clean_url)
                        if response.status_code == 200 and len(response.content) > 1000:
                            product_img = Image.open(io.BytesIO(response.content)).convert("RGBA")
                except Exception as e:
                    logger.warning(f"Failed to download remote product image {clean_url}: {e}")

            # 2. Create base canvas (1080x1080 for Instagram / Facebook post)
            bg_color = brand_colors.get("primary", "#12121e")
            if not bg_color.startswith("#"):
                bg_color = "#" + bg_color
            
            canvas = Image.new("RGB", (1080, 1080), color=bg_color)
            
            # 3. Paste product image if available
            if product_img:
                target_height = int(1080 * 0.7)
                ratio = target_height / max(1, product_img.height)
                target_width = int(product_img.width * ratio)
                
                resized_img = product_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                x_offset = (1080 - target_width) // 2
                y_offset = (1080 - target_height) // 2 - 40
                
                temp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                temp.paste(resized_img, (x_offset, y_offset))
                canvas = Image.alpha_composite(canvas.convert("RGBA"), temp).convert("RGB")
            
            # 4. Draw modern headline & CTA banner
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.load_default()
            
            cta_bg = brand_colors.get("secondary", "#fe2c55")
            if not cta_bg.startswith("#"):
                cta_bg = "#" + cta_bg
                
            # Bottom banner container
            draw.rectangle([(80, 920), (1000, 1020)], fill=cta_bg)
            
            display_text = f"{headline[:45]} | {cta[:30]}" if headline and cta else (headline or cta or "Shop Now")
            draw.text((120, 955), display_text, fill="white", font=font)
            
            # 5. Save locally and return public/relative URL
            filename = f"post_{uuid.uuid4().hex}.jpg"
            filepath = os.path.join(save_dir, filename)
            canvas.save(filepath, "JPEG", quality=90)
            
            # Return dynamically resolved public URL
            return settings.get_public_url(f"/uploads/{filename}")
            
        except Exception as e:
            logger.error(f"Image composition failed: {e}")
            if product_image_url:
                return settings.get_public_url(product_image_url)
            return ""
