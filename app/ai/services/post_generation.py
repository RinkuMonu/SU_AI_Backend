import json
import logging
import os
import re
import io
import uuid
import random
import httpx
from PIL import Image

from app.core.config import settings
from app.ai.prompts.post import build_post_prompt
from app.ai.image.generator import ImageGenerator
from app.utils.image_composer import ImageComposer

_log = logging.getLogger(__name__)


class PostGenerationService:

    def _get_ai_provider(self):
        from app.ai.factory import AIProviderFactory
        return AIProviderFactory.get_provider(preferred="openai", tier="fast")

    async def _load_reference_images(self, reference_images: list[str]) -> list[Image.Image]:
        """Loads and prepares reference images as PIL Image objects for OpenAI."""
        pil_images = []
        for img_ref in (reference_images or [])[:4]:  # limit to top 4 reference images
            if not img_ref or not isinstance(img_ref, str):
                continue
            try:
                # Check if it is a local upload path or URL
                clean_ref = img_ref.strip()
                if "uploads/" in clean_ref:
                    # Extract relative path inside uploads
                    rel_part = clean_ref.split("uploads/")[-1].split("?")[0]
                    local_path = os.path.join(os.getcwd(), "uploads", rel_part)
                    if os.path.exists(local_path):
                        img = Image.open(local_path).convert("RGB")
                        # Downscale large reference images to 1024 max dimension for fast transmission
                        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                        pil_images.append(img)
                        continue

                # If remote HTTP/HTTPS image
                if clean_ref.startswith("http://") or clean_ref.startswith("https://"):
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                        res = await client.get(clean_ref, follow_redirects=True)
                        if res.status_code == 200 and len(res.content) > 1000:
                            img = Image.open(io.BytesIO(res.content)).convert("RGB")
                            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            pil_images.append(img)
            except Exception as e:
                _log.warning(f"Failed to load reference image '{img_ref}': {e}")
        return pil_images

    async def generate_post(
        self,
        business: dict,
        brand: dict,
        product: dict,
        platform: str,
        objective: str,
        language: str,
        additional_instruction: str | None = None,
        reference_images: list[str] | None = None,
        products: list | None = None,
        use_brand_kit: bool = False,
        manual_brand: dict | None = None,
        content_type: str = "post",
        product_images: list[str] | None = None,
    ) -> dict:
        if brand is None:
            brand = {}
        if business is None:
            business = {}
        if product is None:
            product = {}
        if not product and products:
            product = products[0]

        # Combine all product and reference images
        all_refs = []
        for img in (product_images or []) + (reference_images or []):
            if img and img not in all_refs:
                all_refs.append(img)
        # Also include product's own images if present and not in all_refs
        if product.get("image_url") and product.get("image_url") not in all_refs:
            all_refs.insert(0, product.get("image_url"))
        for pimg in product.get("images", []) or []:
            if pimg and pimg not in all_refs:
                all_refs.append(pimg)

        pil_refs = await self._load_reference_images(all_refs)
        has_refs = len(pil_refs) > 0

        provider = self._get_ai_provider()
        extracted_subject = product.get("name") if product and product.get("name") else None
        extracted_traits = None

        # Step 1: Accurate Subject & Trait Extraction via OpenAI Multimodal Vision (gpt-4.1-mini)
        if has_refs:
            vision_prompt = (
                "Examine this reference image with extreme visual precision.\n"
                "Identify:\n"
                "1. Exact Primary Subject (exact name if historical figure, deity, celebrity, or exact product type/garment/item):\n"
                "2. Key visual traits (clothing, face, glasses, distinctive colors, textures):\n"
                "Return ONLY a JSON object: {\"subject_name\": \"...\", \"key_traits\": \"...\"}"
            )
            try:
                v_res = await provider.generate_text(
                    prompt=vision_prompt,
                    images=pil_refs,
                    system_prompt="You are a multimodal vision analyst. Return ONLY valid JSON."
                )
                v_text = v_res.get("text", "").strip() if isinstance(v_res, dict) else str(v_res).strip()
                if v_text:
                    v_clean = v_text.replace("```json", "").replace("```", "")
                    v_match = re.search(r'\{.*\}', v_clean, re.DOTALL)
                    if v_match:
                        v_json = json.loads(v_match.group(0))
                        extracted_subject = v_json.get("subject_name") or extracted_subject
                        extracted_traits = v_json.get("key_traits")
                        _log.info(f"OpenAI vision identified reference subject: '{extracted_subject}'")
            except Exception as e:
                _log.warning(f"OpenAI vision extraction note: {e}")

        # Step 2: Build Content Prompt with the identified subject and product features anchored
        prompt = build_post_prompt(
            business=business,
            brand=brand,
            product=product,
            products=products,
            platform=platform,
            objective=objective,
            language=language,
            additional_instruction=additional_instruction,
            has_reference_images=has_refs,
            extracted_subject=extracted_subject,
            extracted_traits=extracted_traits,
            use_brand_kit=use_brand_kit,
            manual_brand=manual_brand,
            content_type=content_type,
        )

        raw_text = ""
        try:
            _log.info(f"Calling OpenAI GPT-4.1 Mini for {content_type} content...")
            c_res = await provider.generate_text(
                prompt=prompt,
                images=pil_refs if has_refs else None,
                system_prompt="You are an expert social media and content marketing strategist. Return ONLY valid JSON."
            )
            raw_text = c_res.get("text", "").strip() if isinstance(c_res, dict) else str(c_res).strip()
            _log.info("OpenAI content generation succeeded")
        except Exception as e:
            _log.warning(f"OpenAI content generation error: {e}")

        # Clean JSON markdown formatting
        cleaned_json = raw_text
        if "```json" in cleaned_json:
            cleaned_json = cleaned_json.split("```json")[-1].split("```")[0].strip()
        elif "```" in cleaned_json:
            cleaned_json = cleaned_json.split("```")[1].strip()

        parsed = {}
        try:
            parsed = json.loads(cleaned_json)
        except Exception:
            json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                except Exception:
                    pass

        default_headline = f"{extracted_subject or product.get('name', 'Special Offer')} ✨"
        if not parsed or not isinstance(parsed, dict):
            prod_features_summary = ", ".join(product.get("features", [])) if product.get("features") else "exceptional quality and design"
            default_caption = f"Discover the all-new {product.get('name', 'collection')} crafted for excellence. Featuring {prod_features_summary}."
            if product.get("price"):
                default_caption += f" Available now for only {product.get('price')}."
            parsed = {
                "headline": default_headline,
                "caption": default_caption,
                "call_to_action": "Shop Now | Link in Bio",
                "hashtags": ["#trending", "#newlaunch", "#lifestyle", "#quality"],
                "creative_direction": additional_instruction or "Studio commercial product photography",
                "image_prompt": f"Raw authentic commercial photography of {product.get('name', 'the product')}, 8k resolution, cinematic lighting"
            }

        # Ensure all expected fields exist
        parsed.setdefault("headline", default_headline)
        parsed.setdefault("caption", "Discover unmatched craftsmanship and style.")
        parsed.setdefault("call_to_action", "Tap the link in bio to explore.")
        parsed.setdefault("hashtags", ["#trending", "#viral", "#lifestyle"])
        parsed.setdefault("creative_direction", "")

        # If ad, ensure primary_text and description exist
        if content_type in ["ad", "advertisement"]:
            if not parsed.get("primary_text"):
                parsed["primary_text"] = parsed.get("caption")
            if not parsed.get("description"):
                parsed["description"] = f"Explore {product.get('name', 'our top rated product')} today."

        # ---------------------------------------------------------------------
        # Image Generation & Composition
        # ---------------------------------------------------------------------
        clean_type = (content_type or "post").lower()
        image_url = ""

        # For captions: If user already provided product image(s), reuse the primary product image
        if clean_type == "caption" and all_refs:
            image_url = all_refs[0]
            _log.info(f"Reusing existing product image for caption: {image_url}")
        else:
            # Anchor the image_prompt on the extracted subject & product
            img_prompt = (parsed.get("image_prompt") or parsed.get("creative_direction") or "").strip()

            if extracted_subject:
                if extracted_subject.lower() not in img_prompt.lower():
                    img_prompt = (
                        f"Raw authentic photograph of {extracted_subject}, {extracted_traits or ''}, "
                        f"{additional_instruction or 'cinematic lighting, elegant lifestyle'}, natural warm lighting, "
                        f"photorealistic textures, 8k resolution, authentic likeness, "
                        f"strictly no Chinese face, no East Asian face, no porcelain doll face, no anime, no cartoon, no 3d render"
                    )
                elif not img_prompt.lower().startswith("raw authentic"):
                    img_prompt = f"Raw authentic photograph of {img_prompt}"
            else:
                base_prompt = img_prompt or additional_instruction or product.get("name") or "commercial high quality social media photography"
                human_terms = ["woman", "women", "girl", "girls", "man", "men", "boy", "person", "people", "portrait", "face", "model", "holi", "diwali", "festiv", "saree", "lehenga", "ethnic"]
                if any(k in base_prompt.lower() for k in human_terms):
                    if "indian" not in base_prompt.lower():
                        img_prompt = (
                            f"Raw authentic photograph of authentic Indian people, {base_prompt}, "
                            f"genuine South Asian Indian facial features, warm wheatish Indian skin tone, dark brown eyes, "
                            f"natural lighting, 8k resolution, documentary photography, "
                            f"strictly no Chinese face, no East Asian face, no porcelain doll face, no anime, no cartoon, no 3d render"
                        )
                    else:
                        img_prompt = (
                            f"{base_prompt}, genuine South Asian Indian facial features, warm Indian skin tone, "
                            f"strictly no Chinese face, no East Asian face, no porcelain doll face, no anime, no cartoon, no 3d render"
                        )
                else:
                    img_prompt = base_prompt

            # If Brand Kit mode is enabled, incorporate brand styling and colors into image prompt
            if use_brand_kit and brand and any(brand.values()):
                b_style = brand.get("visual_style") or brand.get("social_style")
                b_color = brand.get("primary_color")
                brand_visual_directives = []
                if b_style:
                    brand_visual_directives.append(f"aesthetic style: {b_style}")
                if b_color:
                    brand_visual_directives.append(f"brand color harmony accents of {b_color}")
                if brand_visual_directives:
                    img_prompt = f"{img_prompt}, {', '.join(brand_visual_directives)}"
            elif not use_brand_kit and manual_brand and manual_brand.get("brand_colors"):
                m_colors = manual_brand.get("brand_colors")
                color_str = ", ".join(m_colors) if isinstance(m_colors, list) else str(m_colors)
                img_prompt = f"{img_prompt}, subtle color accents of {color_str}"

            _log.info(f"Final image generation prompt: {img_prompt[:200]}...")

            image_gen = ImageGenerator()
            seed = random.randint(1000, 999999)
            try:
                img_res = await image_gen.generate(
                    prompt=img_prompt,
                    aspect_ratio="1:1",
                    seed=seed,
                    pil_refs=pil_refs
                )
                image_url = img_res.get("image_url", "")
            except Exception as e:
                _log.error(f"Image generation failed: {e}")
                # Fallback to existing product image if available
                image_url = all_refs[0] if all_refs else ""

        # Apply saved brand logo overlay if Brand Kit mode is active and logo is available
        logo_applied = False
        logo_unavailable = False
        if use_brand_kit and brand and any(brand.values()):
            brand_logo = brand.get("logo_url")
            if brand_logo and image_url:
                try:
                    overlay_url = await ImageComposer.apply_logo_overlay(
                        image_url_or_path=image_url,
                        logo_url_or_path=brand_logo,
                        position="top_right"
                    )
                    if overlay_url and overlay_url != image_url:
                        image_url = overlay_url
                        logo_applied = True
                except Exception as logo_err:
                    _log.warning(f"Could not apply logo overlay: {logo_err}")
            elif not brand_logo:
                logo_unavailable = True

        # Assign media URLs and metadata
        parsed["content_type"] = content_type
        parsed["image_url"] = image_url
        parsed["media_url"] = image_url
        parsed["use_brand_kit"] = use_brand_kit
        parsed["brand_kit_applied"] = bool(use_brand_kit and brand and any(brand.values()))

        if use_brand_kit and brand and any(brand.values()):
            parsed["brand_details"] = {
                "brand_name": brand.get("brand_name") or brand.get("business_name"),
                "primary_color": brand.get("primary_color"),
                "secondary_color": brand.get("secondary_color"),
                "accent_color": brand.get("accent_color"),
                "font": brand.get("font") or brand.get("heading_font"),
                "brand_voice": brand.get("brand_voice") or brand.get("tone"),
                "visual_style": brand.get("visual_style") or brand.get("social_style"),
                "logo_url": brand.get("logo_url"),
                "logo_applied": logo_applied,
                "logo_unavailable": logo_unavailable,
                "tagline": brand.get("tagline"),
            }
        elif not use_brand_kit and manual_brand:
            parsed["manual_branding_applied"] = True
            parsed["manual_brand"] = manual_brand

        return parsed
