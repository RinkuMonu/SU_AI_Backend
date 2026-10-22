import json
from typing import Optional, Dict, Any

def detect_product_domain(product_name: str, category: str = "", description: str = "") -> str:
    combined = f"{product_name} {category} {description}".lower()
    
    if any(k in combined for k in ["laptop", "macbook", "computer", "notebook", "pc", "desktop", "monitor", "keyboard", "mouse", "gpu", "processor"]):
        return "laptop_computer"
    if any(k in combined for k in ["earbuds", "headphone", "smartwatch", "watch", "tablet", "ipad", "gadget", "charger", "audio", "drone", "camera"]):
        return "electronics_tech"
    if any(k in combined for k in ["sofa", "couch", "chair", "bed", "wardrobe", "table", "desk", "dining table", "recliner", "bookshelf", "cabinet", "furniture", "living room", "bedroom", "mattress", "cushion", "velvet", "upholstery"]):
        return "furniture_interior"
    if any(k in combined for k in ["saree", "sari", "banarasi", "kanjivaram", "chanderi", "paithani", "silk"]):
        return "saree_ethnic"
    if any(k in combined for k in ["lehenga", "choli", "anarkali", "sherwani", "kurta", "ethnic wear", "bridal wear"]):
        return "lehenga_ethnic"
    if any(k in combined for k in ["hoodie", "tshirt", "t-shirt", "jacket", "jeans", "streetwear", "sneaker", "shoes", "pants", "suit", "blazer", "dress", "clothing"]):
        return "fashion_streetwear"
    if any(k in combined for k in ["serum", "cream", "lotion", "moisturizer", "skincare", "skin care", "sunscreen", "cleanser", "toner", "face wash"]):
        return "skincare_beauty"
    if any(k in combined for k in ["lipstick", "foundation", "eyeliner", "mascara", "makeup", "cosmetic", "blush", "perfume", "fragrance", "cologne"]):
        return "cosmetics_fragrance"
    if any(k in combined for k in ["jewelry", "jewellery", "necklace", "choker", "earring", "ring", "bangle", "bracelet", "gold jewellery", "diamond", "polki", "pendant"]):
        return "jewellery_luxury"
    if any(k in combined for k in ["coffee", "tea", "biryani", "burger", "pizza", "restaurant", "cafe", "food", "snack", "beverage", "bakery", "cake", "dining"]):
        return "food_dining"
    if any(k in combined for k in ["fitness", "gym", "workout", "protein", "supplement", "yoga", "training"]):
        return "fitness_health"
    if any(k in combined for k in ["hotel", "resort", "travel", "tour", "vacation", "villa", "property", "real estate"]):
        return "travel_realestate"
    
    return "general_product"


def get_reel_script_prompt(
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
    festival_theme: str = "none"
) -> str:
    prod_name = product.get("name", "Product")
    prod_desc = product.get("description", "")
    prod_price = product.get("price", "")
    prod_category = product.get("category", "") or "Commercial Product"
    business_name = brand.get("business_name") or brand.get("name") or "SevenUnique Partner"
    primary_color = brand.get("primary_color", "#7928CA")

    domain = detect_product_domain(prod_name, prod_category, prod_desc)
    is_festival_explicit = bool(festival_theme and festival_theme.lower() not in ["none", "null", "false", ""])

    # 1. Domain-specific guidance tailored strictly to this product
    if domain in ["laptop_computer", "electronics_tech"]:
        domain_directives = f"""
# DOMAIN FOCUS: ELECTRONICS & TECH HARDWARE
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Sleek metallic/matte chassis, keyboard typing close-up, vivid high-refresh screen display, port details, ergonomic usage at a modern desk or professional creative workspace, precision hinge movement, ambient tech studio lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show sarees, lehengas, bridal clothing, lipstick, cosmetic creams, jewellery, food, or traditional wedding rituals. The product must look like a high-end tech commercial.
"""
    elif domain in ["saree_ethnic", "lehenga_ethnic"]:
        domain_directives = f"""
# DOMAIN FOCUS: ETHNIC APPAREL & FASHION
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Luxurious fabric texture, intricate embroidery or zari work, graceful drape, garment movement, model styling in high-fashion studio or elegant architectural setting.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, computers, tech gadgets, cosmetic droppers, or unrelated electronics. Keep the focus entirely on this fashion garment.
"""
    elif domain in ["skincare_beauty", "cosmetics_fragrance"]:
        domain_directives = f"""
# DOMAIN FOCUS: SKINCARE & BEAUTY
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Product packaging bottle/jar, creamy or liquid droplet texture, clean vanity aesthetic, dewy skin radiance, delicate application, soft morning or studio diffused lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, computers, lehengas, sarees, clothing fashion, or food.
"""
    elif domain == "food_dining":
        domain_directives = f"""
# DOMAIN FOCUS: FOOD, BEVERAGE & DINING
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Appetizing fresh steam, garnish drizzle, rich sauce texture, fresh ingredients, sizzling preparation, appetizing plating, warm ambient cafe/restaurant lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, clothing fashion, sarees, cosmetics, or electronics.
"""
    elif domain == "jewellery_luxury":
        domain_directives = f"""
# DOMAIN FOCUS: LUXURY JEWELLERY
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Precious metal luster, gemstone/diamond facet sparkle, velvet pedestal presentation, delicate neck/wrist placement, optical light sweeps.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, computers, casual clothes, or food.
"""
    elif domain == "furniture_interior":
        domain_directives = f"""
# DOMAIN FOCUS: LUXURY FURNITURE & INTERIOR DESIGN
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS & CAMERA DIRECTIVES:
  * SCENE 1 (Wide Establishing Shot): Elegant modern architectural living room or sunlit luxury penthouse with herringbone hardwood floors, natural ambient daylight, tasteful minimalist decor. Camera: lateral dolly tracking glide showing '{prod_name}' as the majestic centerpiece.
  * SCENE 2 (Three-Quarter Perspective): Three-quarter depth angle revealing the refined profile, comfortable deep cushions, tailored armrests, brass/solid-wood legs, and structural silhouette of '{prod_name}'. Camera: smooth controlled push-in reveal.
  * SCENE 3 (Macro Craftsmanship & Material Texture): Extreme macro close-up showcasing authentic fabric texture (rich velvet pile, grain, tailored seams, double-piped upholstery stitches), with soft grazing light and shallow depth of field. Camera: diagonal macro texture drift.
  * SCENE 4 (Hero Commercial Finale): High-impact low-angle hero showcase of '{prod_name}' in warm golden hour sunlight, exuding comfort, timeless craftsmanship, and luxury lifestyle, with clean breathing space for brand logo and CTA.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, sarees, lehengas, cosmetics, food, or clutter. The commercial must look like an official high-end European furniture commercial (e.g., West Elm, B&B Italia, Restoration Hardware).
"""
    else:
        domain_directives = f"""
# DOMAIN FOCUS: {prod_category.upper()}
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Authentic showcase of '{prod_name}' highlighting {prod_desc or 'its premium quality and design'}, realistic usage in an appropriate modern setting.
- FORBIDDEN VISUALS: Strictly DO NOT mix unrelated products from other categories. Every scene must feature '{prod_name}'.
"""

    # 2. Festival theme guidance
    if is_festival_explicit:
        festival_directives = f"""
# FESTIVAL CAMPAIGN: {festival_theme.upper()} (EXPLICITLY REQUESTED)
- This is a dedicated {festival_theme.title()} promotional campaign for '{prod_name}'.
- Complement the product with tasteful {festival_theme.title()} atmosphere (e.g., warm festive celebratory lights, festive greeting or festive offer '{offer or 'Special Festive Offer'}').
- CRITICAL: '{prod_name}' MUST remain the primary commercial hero product. Do NOT replace the product with festival clipart.
"""
    else:
        festival_directives = """
# STRICT FESTIVAL & SEASONAL EXCLUSION
- The user has NOT requested a festival theme.
- ABSOLUTELY FORBIDDEN: Do NOT add Diwali diyas, rangoli, firecrackers, Holi colors, Eid crescents, Christmas decor, or wedding rituals.
- The environment MUST be a clean, modern, professional commercial setting appropriate for the product.
"""

    # 3. Generation mode rules
    if generation_mode in ["prompt", "veo"]:
        user_p = product.get("prompt") or product.get("custom_prompt") or additional_instruction or prod_name
        v_style = product.get("video_style", "Cinematic 8K Photoreal")
        mode_directives = f"""
# GENERATION MODE: AI PROMPT TO REEL (GOOGLE VEO 3.1 & GEMINI STUDIO)
- THE CORE CREATIVE VISION: "{user_p}"
- VISUAL STYLE: {v_style}
- This is a custom AI-directed reel brought to life directly from the user's prompt.
- Create dynamic, visually stunning scenes that faithfully interpret the prompt.
- Ensure 'veo_video_prompt' is a high-fidelity Veo 3.1 generation prompt (9:16 vertical video, cinematic camera movement, realistic physics, lighting, and textures).
"""
    elif generation_mode == "creative":
        mode_directives = f"""
# GENERATION MODE: CREATIVE / EXPERIMENTAL
- The user requested creative storytelling.
- If a product is specified ('{prod_name}'), build an innovative, high-aesthetic concept around it without introducing competing commercial products.
"""
    else:
        mode_directives = f"""
# GENERATION MODE: PRODUCT-FOCUSED COMMERCIAL (STRICT CONTEXT LOCK)
- Every single scene (Scene 1 to end) MUST feature '{prod_name}' as the primary subject.
- Maintain consistent product identity, color, and category across the entire reel.
- Creative freedom applies to camera movements (push-in, pan, orbit, macro), lighting, and realistic interactions—NEVER to changing the product.
"""

    prompt = f"""You are an elite Commercial Director and AI Video Producer.
Generate a structured, photorealistic 9:16 Instagram Reel plan strictly focused on this product.

# PRODUCT CONTEXT LOCK (CANNOT BE CHANGED)
- Product Name: {prod_name}
- Product Category: {prod_category}
- Product Description / USPs: {prod_desc or f"Premium {prod_name}"}
- Listed Price: {prod_price if prod_price else "Exclusive"}
- Business / Brand Name: {business_name}
- Brand Color: {primary_color}

# CAMPAIGN SPECIFICATIONS
- Advertising Objective: {objective}
- Platform: {platform} (9:16 vertical video)
- Target Duration: {duration} seconds
- Spoken Language: {language}
- Campaign Tone: {tone}
"""
    if offer:
        prompt += f"- Promotional Offer: {offer}\n"
    if additional_instruction:
        prompt += f"- User Instructions / Custom Prompt: {additional_instruction}\n"

    prompt += f"""
{mode_directives}
{domain_directives}
{festival_directives}

# HOOK & ON-SCREEN TEXT GUIDELINES (TAILORED TO {prod_name.upper()})
- "hook_headline": 2-3 word curiosity callout (e.g. "Meet the new...", "Upgrade your...", "Experience ultimate...", "Stop scrolling! 🛑")
- "hook_highlight": High-impact payoff focused strictly on {prod_name} (2-4 words, e.g. "{prod_name} 🔥", "Limited Drop ✨")
- "hook": Full combined hook text.
- "on_screen_text": SHORT and PUNCHY (2 to 4 words max per scene).
- "voiceover": High-converting spoken audio script in {language} about {prod_name}.
- "trending_audio": Realistic viral audio track fitting {prod_category}.
- "creator_name": Commercial brand creator handle relevant to {business_name}.

# REQUIRED JSON SCHEMA
Return ONLY a valid JSON object matching this exact schema:
{{
  "title": "string",
  "advertising_objective": "{objective}",
  "primary_product": "{prod_name}",
  "product_category": "{prod_category}",
  "generation_mode": "{generation_mode}",
  "festival_theme": "{festival_theme if is_festival_explicit else 'none'}",
  "visual_concept": "string (visual concept focused exclusively on {prod_name})",
  "style_direction": "string (lighting, color palette, composition)",
  "target_audience": "string",
  "hook": "string",
  "hook_headline": "string (2-3 words)",
  "hook_highlight": "string (2-4 words)",
  "trending_audio": "string",
  "creator_name": "string",
  "follower_count": "24.8K followers",
  "likes_count": "28.5K",
  "comments_count": "890",
  "duration_seconds": {duration},
  "language": "{language}",
  "tone": "{tone}",
  "veo_video_prompt": "string (master 9:16 vertical Veo prompt focused strictly on {prod_name})",
  "negative_constraints": "unrelated products, blurry, low resolution, morphing shapes, extra fingers, cartoonish, flicker, watermark",
  "scenes": [
    {{
      "scene_number": 1,
      "duration_seconds": 4,
      "main_subject": "{prod_name}",
      "product_identity": "{prod_name}",
      "visual": "string (detailed description of scene featuring {prod_name})",
      "camera_movement": "string (e.g. slow cinematic push-in, low-angle orbit, macro pan)",
      "lighting_environment": "string",
      "product_interaction": "string",
      "voiceover": "string",
      "on_screen_text": "string (2-4 words only)",
      "transition": "fade",
      "veo_prompt": "string (Veo video prompt for this scene featuring {prod_name})",
      "negative_prompt": "unrelated products, blurry, low quality, morphing objects"
    }}
  ],
  "cta": "string (e.g., Shop {prod_name} today!)",
  "caption": "string (Instagram caption with bullet points about {prod_name})",
  "hashtags": ["string"]
}}

DO NOT return any commentary or text outside of the JSON object.
"""
    return prompt
