import json
import logging
import re
from typing import Optional, Dict, Any, List

from app.ai.factory import AIProviderFactory
from app.ai.prompts.reel import get_reel_script_prompt, detect_product_domain
from app.schemas.reel import ReelScript, ReelScene

logger = logging.getLogger(__name__)

FORBIDDEN_KEYWORDS_MAP = {
    "laptop_computer": ["saree", "sari", "lehenga", "choli", "dupatta", "zari", "lipstick", "mascara", "skincare", "serum", "necklace", "biryani"],
    "electronics_tech": ["saree", "sari", "lehenga", "choli", "dupatta", "zari", "lipstick", "mascara", "skincare", "serum", "necklace", "biryani"],
    "saree_ethnic": ["laptop", "macbook", "computer", "notebook", "desktop", "motherboard", "processor", "smartwatch", "lipstick", "serum", "biryani"],
    "lehenga_ethnic": ["laptop", "macbook", "computer", "notebook", "desktop", "motherboard", "processor", "smartwatch", "lipstick", "serum", "biryani"],
    "skincare_beauty": ["laptop", "macbook", "computer", "saree", "lehenga", "biryani", "burger", "pizza", "shoes", "sneakers"],
    "cosmetics_fragrance": ["laptop", "macbook", "computer", "saree", "lehenga", "biryani", "burger", "pizza"],
    "food_dining": ["laptop", "macbook", "computer", "saree", "lehenga", "lipstick", "serum", "diamond ring", "necklace"],
    "jewellery_luxury": ["laptop", "macbook", "computer", "saree", "lehenga", "food", "burger", "biryani"]
}

FESTIVAL_KEYWORDS = ["diwali", "diya", "diyas", "rangoli", "firecrackers", "patakhe", "holi", "eid", "christmas", "santa"]


def validate_and_sanitize_storyboard(script: ReelScript, product: dict, festival_theme: str = "none") -> ReelScript:
    """
    Validates every scene against the locked product context and requested festival theme.
    Corrects any scene contamination before it can reach the video generator.
    """
    prod_name = product.get("name", "Product")
    prod_cat = product.get("category", "")
    prod_desc = product.get("description", "")
    domain = detect_product_domain(prod_name, prod_cat, prod_desc)
    forbidden_words = FORBIDDEN_KEYWORDS_MAP.get(domain, [])

    is_festival_allowed = bool(festival_theme and festival_theme.lower() not in ["none", "null", "false", ""])

    script.primary_product = prod_name
    script.product_category = prod_cat

    sanitized_scenes = []
    for sc in script.scenes:
        visual_text = (sc.visual or "").lower()
        voice_text = (sc.voiceover or "").lower()
        veo_text = (sc.veo_prompt or "").lower()

        # Check for cross-category contamination
        has_forbidden_category = any(fw in visual_text or fw in voice_text or fw in veo_text for fw in forbidden_words)
        
        # Check for unrequested festival contamination
        has_unrequested_festival = False
        if not is_festival_allowed:
            has_unrequested_festival = any(fk in visual_text or fk in voice_text or fk in veo_text for fk in FESTIVAL_KEYWORDS)

        if has_forbidden_category or has_unrequested_festival:
            logger.warning(
                f"Scene {sc.scene_number} violated product context rules (forbidden_cat={has_forbidden_category}, "
                f"unrequested_fest={has_unrequested_festival}). Sanitizing scene to lock on '{prod_name}'."
            )
            # Recondition visual and prompts strictly to the target product
            sc.visual = f"Cinematic detailed showcase of {prod_name}, highlighting authentic features and premium design in a professional studio setting."
            sc.veo_prompt = (
                f"Photorealistic 9:16 vertical commercial advertisement of {prod_name}, "
                f"cinematic studio lighting, smooth camera movement, highly detailed surface texture."
            )
            sc.negative_prompt = (
                f"unrelated products, {', '.join(forbidden_words[:4])}, blurry, distorted, low quality, morphing objects"
            )

        sc.main_subject = prod_name
        sc.product_identity = prod_name
        sanitized_scenes.append(sc)

    script.scenes = sanitized_scenes
    return script


class ReelScriptService:
    def __init__(self):
        self.provider = AIProviderFactory.get_provider()

    @staticmethod
    def _unwrap_parsed(parsed: Any) -> Optional[Dict[str, Any]]:
        if not parsed:
            return None
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            parsed = parsed[0]
        if isinstance(parsed, dict):
            if "scenes" in parsed or "title" in parsed:
                return parsed
            # Check if wrapped in a single key like {"product_name": {...}} or {"data": {...}}
            for val in parsed.values():
                if isinstance(val, dict) and ("scenes" in val or "title" in val or "primary_product" in val):
                    return val
            return parsed
        return None

    @classmethod
    def _extract_and_parse_json(cls, content: str) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        content = content.strip()

        # 1. Try json_repair directly
        try:
            import json_repair
            parsed = json_repair.loads(content)
            unwrapped = cls._unwrap_parsed(parsed)
            if unwrapped:
                return unwrapped
        except Exception:
            pass

        # 2. Standard json.loads
        try:
            parsed = json.loads(content)
            unwrapped = cls._unwrap_parsed(parsed)
            if unwrapped:
                return unwrapped
        except Exception:
            pass

        # 3. Extract markdown code fences ```json ... ```
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        candidate = match.group(1).strip() if match else content

        try:
            import json_repair
            parsed = json_repair.loads(candidate)
            unwrapped = cls._unwrap_parsed(parsed)
            if unwrapped:
                return unwrapped
        except Exception:
            pass

        try:
            parsed = json.loads(candidate)
            unwrapped = cls._unwrap_parsed(parsed)
            if unwrapped:
                return unwrapped
        except Exception:
            pass

        # 4. Extract from first '{' to last '}'
        start_idx = candidate.find('{')
        end_idx = candidate.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            slice_text = candidate[start_idx:end_idx+1]
            try:
                import json_repair
                parsed = json_repair.loads(slice_text)
                unwrapped = cls._unwrap_parsed(parsed)
                if unwrapped:
                    return unwrapped
            except Exception:
                pass
            try:
                parsed = json.loads(slice_text)
                unwrapped = cls._unwrap_parsed(parsed)
                if unwrapped:
                    return unwrapped
            except Exception:
                pass

        # 5. If truncated, repair from first '{' to end
        if start_idx != -1:
            tail_text = candidate[start_idx:]
            try:
                import json_repair
                parsed = json_repair.loads(tail_text)
                unwrapped = cls._unwrap_parsed(parsed)
                if unwrapped:
                    return unwrapped
            except Exception:
                pass

        return None

    async def generate_script(
        self,
        product: dict,
        brand: dict,
        objective: str,
        platform: str,
        duration: int,
        language: str,
        tone: str,
        offer: str = None,
        additional_instruction: str = None,
        generation_mode: str = "product",
        festival_theme: str = "none",
        use_brand_kit: bool = False
    ) -> ReelScript:
        prompt = get_reel_script_prompt(
            product=product,
            brand=brand,
            objective=objective,
            platform=platform,
            duration=duration,
            language=language,
            tone=tone,
            offer=offer,
            additional_instruction=additional_instruction,
            generation_mode=generation_mode,
            festival_theme=festival_theme,
            use_brand_kit=use_brand_kit
        )
        
        system_prompt = (
            "You are a professional commercial film director and storyboard producer. "
            "Lock all creative output exclusively to the specified product. Output only valid JSON."
        )
        
        try:
            response = await self.provider.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                response_format={"type": "json_object"},
                max_tokens=3000
            )
            
            content = response.get("text", "").strip()
            
            parsed_json = self._extract_and_parse_json(content)
            if not parsed_json:
                raise ValueError(f"Could not parse valid JSON from AI response: {content[:200]}")
            # Validate with Pydantic
            script = ReelScript(**parsed_json)

            # Enforce Product Context Storyboard Validation
            script = validate_and_sanitize_storyboard(script, product, festival_theme)

            return script
            
        except Exception as e:
            logger.error(f"Error generating reel script/plan: {e}")
            raise e
