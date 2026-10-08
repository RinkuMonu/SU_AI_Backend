import json

from app.ai.prompts.post import build_post_prompt
from app.ai.factory import AIProviderFactory


class PostGenerationService:

    async def generate_post(
        self,
        business: dict,
        brand: dict,
        product: dict,
        products: list,
        platform: str,
        objective: str,
        language: str,
        additional_instruction: str | None = None,
    ):
        # Ensure brand is always a dict (get_brand_kit can return None)
        if brand is None:
            brand = {}

        prompt = build_post_prompt(
            business=business,
            brand=brand,
            product=product,
            products=products,
            platform=platform,
            objective=objective,
            language=language,
            additional_instruction=additional_instruction,
        )

        provider = AIProviderFactory.get_provider()
        response = await provider.generate_text(prompt=prompt)
        raw_text = response.get("text", "") if isinstance(response, dict) else str(response)

        # Strip markdown code blocks if present
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].strip()

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = {
                "headline": "",
                "caption": raw_text,
                "call_to_action": "",
                "hashtags": [],
                "creative_direction": "",
            }

        import logging
        _log = logging.getLogger(__name__)

        # Generate image
        image_url = product.get("image_url", "")

        if not image_url:
            from app.ai.image.generator import ImageGenerator
            from app.core.config import settings
            image_gen = ImageGenerator(
                api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
                api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
            )
            prompt_subject = (
                parsed.get("creative_direction", "")
                or product.get("description", "")
                or product.get("name", "product")
            )
            img_prompt = (
                f"Professional social media image about: {prompt_subject}. "
                "Vibrant colors, high quality, photorealistic, 8k."
            )
            try:
                img_res = await image_gen.generate(prompt=img_prompt)
                image_url = img_res.get("image_url", "")
            except Exception as e:
                _log.error(f"Failed to generate image: {e}")
                image_url = ""

        if image_url:
            # Directly use the generated URL — ImageComposer download can be slow/flaky
            # Try to compose a branded banner; fall back to raw URL on any error
            try:
                import asyncio
                from app.utils.image_composer import ImageComposer
                brand_colors = brand.get("colors", {}) if isinstance(brand, dict) else {}
                banner_url = await asyncio.wait_for(
                    ImageComposer.generate_banner(
                        product_image_url=image_url,
                        headline=parsed.get("headline", "New Post!"),
                        cta=parsed.get("call_to_action", "Read More"),
                        brand_colors=brand_colors,
                    ),
                    timeout=15.0,
                )
                parsed["media_url"] = banner_url
                parsed["image_url"] = banner_url
            except Exception as e:
                _log.warning(f"ImageComposer failed, using raw image URL: {e}")
                parsed["media_url"] = image_url
                parsed["image_url"] = image_url

        return parsed