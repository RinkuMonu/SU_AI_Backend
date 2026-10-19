import json
from typing import Optional, Dict, Any

def detect_product_domain(product_name: str, category: str = "", description: str = "") -> str:
    combined = f"{product_name} {category} {description}".lower()
    
    # 1. Food, Gourmet & Dining
    if any(k in combined for k in [
        "burger", "smash", "patty", "cheddar", "bacon", "pizza", "biryani", "food", "dining",
        "snack", "dish", "cuisine", "restaurant", "cafe", "beverage", "drink", "coffee", "tea",
        "cake", "bakery", "dessert", "sandwich", "fries", "tacos", "pasta", "meal", "delicious",
        "artisanal", "flavor", "crispy", "juicy", "sauce", "bun", "culinary", "chocolate", "sweet"
    ]):
        return "food_dining"

    # 2. Automotive & High-Performance Cars
    if any(k in combined for k in [
        "hypercar", "supercar", "car", "automobile", "vehicle", "sports car", "race car",
        "porsche", "ferrari", "lamborghini", "bmw", "mercedes", "tesla", "motorcycle", "bike", "drifting",
        "highway drive", "speedometer", "exhaust"
    ]):
        return "automotive_cars"

    # 3. Sports & Athletics
    if any(k in combined for k in [
        "sprinter", "runner", "running", "athlete", "athletic", "marathon", "track and field",
        "olympic", "stadium", "sprint", "pushing off starting blocks"
    ]):
        return "sports_fitness"

    # 4. Indian Festivals & Cultural Celebrations
    if any(k in combined for k in [
        "diwali", "deepavali", "sparkler", "phuljhadi", "diya", "diyas", "firecracker", "fireworks",
        "holi", "gulal", "navratri", "garba", "dandiya", "eid", "christmas", "new year",
        "festival", "festive", "celebration", "puja", "pooja", "raksha bandhan"
    ]):
        return "festive_cultural"

    # 5. Ethnic Fashion (Sarees, Lehengas, Kurtas)
    if any(k in combined for k in ["saree", "sari", "banarasi", "kanjivaram", "chanderi", "paithani", "silk saree", "zari"]):
        return "saree_ethnic"
    if any(k in combined for k in ["lehenga", "choli", "anarkali", "sherwani", "kurta", "ethnic wear", "bridal wear", "garment", "dupatta"]):
        return "lehenga_ethnic"

    # 6. Skincare & Beauty
    if any(k in combined for k in ["serum", "cream", "lotion", "moisturizer", "skincare", "skin care", "sunscreen", "cleanser", "toner", "face wash"]):
        return "skincare_beauty"
    if any(k in combined for k in ["lipstick", "foundation", "eyeliner", "mascara", "makeup", "cosmetic", "blush", "perfume", "fragrance", "cologne"]):
        return "cosmetics_fragrance"

    # 7. Luxury Jewellery (STRICT full terms - NEVER raw 'gold' or 'ring' substring)
    if any(k in combined for k in [
        "jewelry", "jewellery", "necklace", "choker", "earrings", "jhumka",
        "diamond ring", "gold ring", "wedding ring", "finger ring", "bangles", "bracelet",
        "diamond jewelry", "gold jewelry", "polki", "kundan", "precious gems", "diamond facet"
    ]):
        return "jewellery_luxury"

    # 8. High Fashion, Runway & Streetwear
    if any(k in combined for k in [
        "runway", "gown", "haute couture", "fashion show", "couture", "model walking",
        "hoodie", "tshirt", "t-shirt", "jacket", "jeans", "streetwear", "sneaker", "shoes", "pants", "suit", "blazer", "dress", "clothing", "apparel"
    ]):
        return "fashion_streetwear"

    # 9. Fitness & Gym
    if any(k in combined for k in ["fitness", "gym", "workout", "protein", "supplement", "yoga", "training"]):
        return "sports_fitness"

    # 10. Travel & Real Estate
    if any(k in combined for k in ["hotel", "resort", "travel", "tour", "vacation", "villa", "property", "real estate"]):
        return "travel_realestate"

    # 11. Laptops & Computers
    if any(k in combined for k in ["laptop", "macbook", "notebook", "desktop pc", "monitor", "mechanical keyboard", "gpu", "processor"]):
        return "laptop_computer"

    # 12. Consumer Electronics & Gadgets
    if any(k in combined for k in ["earbuds", "earphone", "headphone", "smartwatch", "smart watch", "fitness band", "tablet", "ipad", "power bank", "charger", "gadget", "drone", "bluetooth speaker", "dslr camera", "action camera", "webcam"]):
        return "electronics_tech"
    
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

    # Auto-detect festival from all inputs if not set
    all_text = f"{prod_name} {prod_category} {prod_desc} {additional_instruction or ''} {festival_theme or ''}".lower()
    if not festival_theme or festival_theme.lower() in ["none", "null", "false", ""]:
        for f_name in ["diwali", "deepavali", "holi", "navratri", "eid", "christmas", "new year", "raksha bandhan"]:
            if f_name in all_text:
                festival_theme = "diwali" if ("diwali" in f_name or "deepavali" in f_name) else f_name
                break

    domain = detect_product_domain(prod_name, prod_category, prod_desc)
    is_festival_explicit = bool(festival_theme and festival_theme.lower() not in ["none", "null", "false", ""]) or domain == "festive_cultural"

    # 1. Domain-specific guidance tailored strictly to this product
    if domain in ["laptop_computer", "electronics_tech"]:
        domain_directives = f"""
# DOMAIN FOCUS: ELECTRONICS & TECH HARDWARE
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Sleek metallic/matte chassis, keyboard typing close-up, vivid high-refresh screen display, port details, ergonomic usage at a modern desk or professional creative workspace, precision hinge movement, ambient tech studio lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show sarees, lehengas, bridal clothing, women with jewelry necklaces, laptops, food, or traditional wedding rituals. The product must look like a high-end tech commercial.
"""
    elif domain == "automotive_cars":
        domain_directives = f"""
# DOMAIN FOCUS: AUTOMOTIVE & HIGH-PERFORMANCE SUPERCARS
- The hero subject is strictly the vehicle/car: '{prod_name}'.
- ALLOWED VISUALS: Sleek metallic bodywork reflections, aerodynamic lines, glowing LED headlights/taillights, alloy wheel spin, exhaust flame/heat distortion, dynamic drone tracking shot along scenic highways or racetrack, ocean waves or urban neon in background, high-speed camera motion blur, golden hour or cinematic night lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show sarees, lehengas, bridal clothing, women with jewelry necklaces, laptops, food, or cosmetics. The commercial must look like an official Top Gear / Porsche / Ferrari supercar commercial.
"""
    elif domain == "sports_fitness":
        domain_directives = f"""
# DOMAIN FOCUS: ATHLETICS, SPORTS & FITNESS
- The hero subject is strictly '{prod_name}'.
- ALLOWED VISUALS: Athletic explosive power, sprinter starting blocks, sweat droplets flying in slow-motion, intense focused eyes, running track at dawn, stadium lighting, golden sunrise rim lighting, muscle definition, inspiring athletic motivation.
- FORBIDDEN VISUALS: Strictly DO NOT show sarees, bridal jewelry necklaces, laptops, burgers, or office tech.
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
# DOMAIN FOCUS: GOURMET FOOD, BEVERAGE & DINING
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Sizzling culinary close-ups, steam gently rising, dripping rich sauce or melted cheddar cheese, golden toasted brioche bun, crispy smoked bacon texture, mouthwatering plating, warm restaurant or studio commercial lighting, dynamic macro push-in.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, computers, high-refresh screens, metallic chassis, keyboards, smartwatches, office desks, clothing fashion, sarees, cosmetics, or unrelated tech. Every scene must be 100% appetizing gourmet food.
"""
    elif domain == "festive_cultural" or is_festival_explicit:
        fest_label = festival_theme.upper() if festival_theme and festival_theme.lower() not in ["none", "null"] else "INDIAN FESTIVE"
        domain_directives = f"""
# DOMAIN FOCUS: {fest_label} CELEBRATION
- The commercial focus is strictly celebrating '{prod_name}' or {fest_label} festival.
- ALLOWED VISUALS: Joyful Indian couple/people in authentic festive ethnic attire (mustard yellow silk saree, festive embroidered kurta), lit golden sizzling sparklers (phuljhadi), warm glowing clay diyas, sparkling bokeh fairy lights, authentic festive celebration, happy smiles, warm night ambient lighting.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, modern office tech, cold corporate desks, metallic computer chassis, unrelated gadgets, or Western corporate settings.
"""
    elif domain == "jewellery_luxury":
        domain_directives = f"""
# DOMAIN FOCUS: LUXURY JEWELLERY
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Precious metal luster, gemstone/diamond facet sparkle, velvet pedestal presentation, delicate neck/wrist placement, optical light sweeps.
- FORBIDDEN VISUALS: Strictly DO NOT show laptops, computers, casual clothes, or food.
"""
    else:
        domain_directives = f"""
# DOMAIN FOCUS: {prod_category.upper()}
- The hero product is strictly '{prod_name}'.
- ALLOWED VISUALS: Authentic showcase of '{prod_name}' highlighting {prod_desc or 'its premium quality and design'}, realistic usage in an appropriate modern setting.
- FORBIDDEN VISUALS: Strictly DO NOT mix unrelated products from other categories. Never mention laptops, computer chassis, or tech screens unless this product is actually a computer. Every scene must feature '{prod_name}'.
"""

    # 2. Festival theme guidance
    if is_festival_explicit:
        active_fest = festival_theme if festival_theme and festival_theme.lower() not in ["none", "null"] else "Diwali"
        festival_directives = f"""
# FESTIVAL CAMPAIGN: {active_fest.upper()} (CELEBRATORY ATMOSPHERE)
- This is a dedicated {active_fest.title()} celebratory commercial.
- Complement the visuals with radiant {active_fest.title()} atmosphere (warm festive lights, glowing sparklers/diyas, festive greeting or festive offer '{offer or 'Special Festive Offer'}').
- Visual tone: Warm, celebratory, joyful, authentic Indian cultural elegance.
"""
    else:
        festival_directives = """
# COMMERCIAL CONTEXT
- Maintain a clean, professional, premium commercial atmosphere tailored 100% to this product domain.
"""

    # 3. Generation mode rules
    if generation_mode == "creative":
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

# HOOK & ON-SCREEN TEXT GUIDELINES (TAILORED TO {prod_name.upper()} AND {domain.upper()})
- "hook_headline": 2-3 word high-converting curiosity callout matching {domain} (e.g., for automotive: "Feel the power! 🏎️" or "Pure adrenaline! ⚡"; for sports: "Push limits! 🏆" or "Unstoppable! 🔥"; for food: "Craving this? 🤤" or "Taste perfection! ✨"; for festive: "Happy Diwali! 🪔"; for fashion: "Style drop! ✨"; for tech: "Next-gen tech! ⚡"; or universal: "Stop scrolling! 🛑")
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
