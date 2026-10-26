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

    @staticmethod
    async def apply_logo_overlay(
        image_url_or_path: str,
        logo_url_or_path: str,
        position: str = "top_right",
        max_size: tuple[int, int] = (160, 100),
        padding: int = 40,
    ) -> str:
        """
        Securely and cleanly composites a brand logo onto a generated post image.
        Strictly preserves aspect ratio and avoids stretching.
        Returns the public URL of the composited image.
        """
        if not image_url_or_path or not logo_url_or_path:
            return image_url_or_path

        try:
            save_dir = os.path.join(os.getcwd(), "uploads", "posts")
            os.makedirs(save_dir, exist_ok=True)

            # 1. Load base image
            base_img = None
            clean_base = image_url_or_path.strip()
            if "uploads/" in clean_base:
                rel = clean_base.split("uploads/")[-1].split("?")[0]
                loc = os.path.join(os.getcwd(), "uploads", rel)
                if os.path.exists(loc):
                    base_img = Image.open(loc).convert("RGBA")

            if not base_img and (clean_base.startswith("http://") or clean_base.startswith("https://")):
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(clean_base)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        base_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

            if not base_img:
                logger.warning(f"Could not load base image for logo overlay: {image_url_or_path}")
                return image_url_or_path

            # 2. Load logo image
            logo_img = None
            clean_logo = logo_url_or_path.strip()
            if "uploads/" in clean_logo:
                rel = clean_logo.split("uploads/")[-1].split("?")[0]
                loc = os.path.join(os.getcwd(), "uploads", rel)
                if os.path.exists(loc):
                    logo_img = Image.open(loc).convert("RGBA")

            if not logo_img and (clean_logo.startswith("http://") or clean_logo.startswith("https://")):
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(clean_logo)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        logo_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

            if not logo_img:
                logger.warning(f"Could not load brand logo for overlay: {logo_url_or_path}")
                return image_url_or_path

            # 3. Scale logo preserving aspect ratio
            max_w, max_h = max_size
            logo_ratio = min(max_w / max(1, logo_img.width), max_h / max(1, logo_img.height))
            new_w = max(1, int(logo_img.width * logo_ratio))
            new_h = max(1, int(logo_img.height * logo_ratio))
            scaled_logo = logo_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # 4. Calculate position coordinates
            bw, bh = base_img.size
            if position == "top_left":
                x = padding
                y = padding
            elif position == "bottom_right":
                x = bw - new_w - padding
                y = bh - new_h - padding
            elif position == "bottom_left":
                x = padding
                y = bh - new_h - padding
            else:  # default top_right
                x = bw - new_w - padding
                y = padding

            # 5. Composite logo onto base image
            overlay_layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
            overlay_layer.paste(scaled_logo, (x, y), scaled_logo)
            final_img = Image.alpha_composite(base_img, overlay_layer).convert("RGB")

            # 6. Save composited image
            out_filename = f"post_brand_{uuid.uuid4().hex[:12]}.jpg"
            out_path = os.path.join(save_dir, out_filename)
            final_img.save(out_path, "JPEG", quality=92)

            return settings.get_public_url(f"/uploads/posts/{out_filename}")

        except Exception as e:
            logger.warning(f"Logo overlay failed: {e}. Falling back to unbranded image.")
            return image_url_or_path

