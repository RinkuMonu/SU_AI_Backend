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

_log = logging.getLogger(__name__)


class PostGenerationService:

    def _get_gemini_clients(self):
        clients = []
        import google.genai as genai
        for k in [settings.GEMINI_API_KEY, getattr(settings, "GEMINI_BACKUP_API_KEY", None)]:
            if k and k not in [c[0] for c in clients]:
                try:
                    clients.append((k, genai.Client(api_key=k)))
                except Exception as e:
                    _log.warning(f"Could not initialize google.genai Client for key: {e}")
        return clients

    async def _load_reference_images(self, reference_images: list[str]) -> list[Image.Image]:
        """Loads and prepares reference images as PIL Image objects for Gemini."""
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
    ) -> dict:
        if brand is None:
            brand = {}
        if business is None:
            business = {}
        if product is None:
            product = {}

        reference_images = reference_images or []
        pil_refs = await self._load_reference_images(reference_images)
        has_refs = len(pil_refs) > 0

        clients = self._get_gemini_clients()

        # Priority list of models with proven Gemini API availability
        models_to_try = [
            getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
        ]
        unique_models = []
        for m in models_to_try:
            if m not in unique_models:
                unique_models.append(m)

        extracted_subject = None
        extracted_traits = None

        # Step 1: Accurate Subject & Trait Extraction via Gemini Multimodal Vision
        if clients and has_refs:
            vision_prompt = (
                "Examine this reference image with extreme visual precision.\n"
                "Identify:\n"
                "1. Exact Primary Subject (exact name if historical figure, deity, celebrity, or exact product type/garment/item):\n"
                "2. Key visual traits (clothing, face, glasses, distinctive colors, textures):\n"
                "Return ONLY a JSON object: {\"subject_name\": \"...\", \"key_traits\": \"...\"}"
            )
            for _, client in clients:
                for model_name in unique_models:
                    try:
                        v_res = client.models.generate_content(
                            model=model_name,
                            contents=[*pil_refs, vision_prompt]
                        )
                        if v_res and v_res.text:
                            v_clean = v_res.text.strip().replace("```json", "").replace("```", "")
                            v_match = re.search(r'\{.*\}', v_clean, re.DOTALL)
                            if v_match:
                                v_json = json.loads(v_match.group(0))
                                extracted_subject = v_json.get("subject_name")
                                extracted_traits = v_json.get("key_traits")
                                _log.info(f"Gemini identified reference subject: '{extracted_subject}'")
                                break
                    except Exception as e:
                        _log.warning(f"Vision extraction note on {model_name}: {e}")
                        continue
                if extracted_subject:
                    break

        # Step 2: Build Post Prompt with the identified subject anchored
        prompt = build_post_prompt(
            business=business,
            brand=brand,
            product=product,
            platform=platform,
            objective=objective,
            language=language,
            additional_instruction=additional_instruction,
            has_reference_images=has_refs,
            extracted_subject=extracted_subject,
            extracted_traits=extracted_traits,
        )

        raw_text = ""

        if clients:
            contents = [*pil_refs, prompt] if has_refs else [prompt]
            for _, client in clients:
                for model_name in unique_models:
                    try:
                        _log.info(f"Calling Gemini ({model_name}) for post content...")
                        response = client.models.generate_content(
                            model=model_name,
                            contents=contents
                        )
                        if response and response.text:
                            raw_text = response.text.strip()
                            _log.info(f"Gemini post generation succeeded with model: {model_name}")
                            break
                    except Exception as e:
                        _log.warning(f"Gemini model {model_name} failed: {e}")
                        continue
                if raw_text:
                    break

        # Fallback to AIProviderFactory if client loop didn't yield text
        if not raw_text:
            try:
                from app.ai.factory import AIProviderFactory
                provider = AIProviderFactory.get_provider()
                res = await provider.generate_text(prompt=prompt)
                raw_text = res.get("text", "") if isinstance(res, dict) else str(res)
            except Exception as e:
                _log.error(f"Provider fallback failed: {e}")

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

        default_headline = f"{extracted_subject} ✨" if extracted_subject else (additional_instruction or "New Special Post")
        if not parsed or not isinstance(parsed, dict):
            parsed = {
                "headline": default_headline,
                "caption": raw_text or "Experience the ultimate collection designed to elevate your everyday moments.",
                "call_to_action": "Shop Now | Link in Bio",
                "hashtags": ["#trending", "#festive", "#lifestyle", "#newlaunch"],
                "creative_direction": additional_instruction or "Commercial photoshoot with warm festive lighting",
                "image_prompt": additional_instruction or "Festive commercial photography, 8k resolution, cinematic lighting"
            }

        # Ensure all expected fields exist
        parsed.setdefault("headline", default_headline)
        parsed.setdefault("caption", "Discover unmatched craftsmanship and style.")
        parsed.setdefault("call_to_action", "Tap the link in bio to explore.")
        parsed.setdefault("hashtags", ["#trending", "#viral", "#lifestyle"])
        parsed.setdefault("creative_direction", "")

        # ---------------------------------------------------------------------
        # Anchor the image_prompt on the extracted subject & Indian ethnicity
        # ---------------------------------------------------------------------
        img_prompt = (parsed.get("image_prompt") or parsed.get("creative_direction") or "").strip()

        if extracted_subject:
            # If the generated prompt does not explicitly name the subject, anchor it firmly
            if extracted_subject.lower() not in img_prompt.lower():
                img_prompt = (
                    f"Raw authentic photograph of {extracted_subject}, {extracted_traits or ''}, "
                    f"{additional_instruction or 'cinematic lighting, elegant lifestyle'}, natural warm lighting, "
                    f"authentic Indian facial features, warm Indian skin tone, South Asian ethnicity, "
                    f"photorealistic skin and fabric textures, 8k resolution, authentic likeness, "
                    f"strictly no Chinese face, no East Asian face, no porcelain doll face, no anime, no cartoon, no 3d render"
                )
            elif not img_prompt.lower().startswith("raw authentic"):
                img_prompt = f"Raw authentic photograph of {img_prompt}"
        else:
            base_prompt = img_prompt or additional_instruction or product.get("name") or "commercial high quality social media photography"
            # If prompt touches people/festivals/clothing, ensure Indian ethnicity is enforced
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
            image_url = ""

        # Assign clean image URL (No broken ImageComposer banner overlay, no external watermarks)
        parsed["image_url"] = image_url
        parsed["media_url"] = image_url

        return parsed
