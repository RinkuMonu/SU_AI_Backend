def build_post_prompt(
    business: dict,
    brand: dict,
    product: dict,
    platform: str,
    objective: str,
    language: str,
    additional_instruction: str | None = None,
    products: list | None = None,
    has_reference_images: bool = False,
    extracted_subject: str | None = None,
    extracted_traits: str | None = None,
    use_brand_kit: bool = False,
    manual_brand: dict | None = None,
    content_type: str = "post",
) -> str:
    biz_context = ""
    # Include business info if available
    if business and business.get("name"):
        biz_context = f"""BUSINESS DETAILS:
- Name: {business.get('name', 'Our Brand')}
- Industry: {business.get('industry', 'Retail')}
- Description: {business.get('description', '')}
"""

    brand_context = ""
    if use_brand_kit and brand and any(brand.values()):
        b_name = brand.get("brand_name") or brand.get("business_name") or business.get("name", "Our Brand")
        b_voice = brand.get("brand_voice") or brand.get("tone") or "Inspiring, authentic, premium"
        b_primary = brand.get("primary_color") or "#7928CA"
        b_sec = brand.get("secondary_color") or ""
        b_accent = brand.get("accent_color") or ""
        b_style = brand.get("visual_style") or brand.get("social_style") or "Modern, clean, aesthetic"
        b_tagline = brand.get("tagline") or ""
        b_font = brand.get("font") or brand.get("heading_font") or ""
        b_audience = brand.get("target_audience") or brand.get("customer_type") or ""

        colors_str = f"Primary: {b_primary}"
        if b_sec:
            colors_str += f", Secondary: {b_sec}"
        if b_accent:
            colors_str += f", Accent: {b_accent}"

        brand_context = f"""OFFICIAL BRAND KIT IDENTITY (USE_BRAND_KIT=TRUE):
- Brand Name: {b_name}
- Brand Voice & Tone: {b_voice}
- Visual & Social Style: {b_style}
- Brand Color Palette: {colors_str}
"""
        if b_tagline:
            brand_context += f"- Tagline: {b_tagline}\n"
        if b_font:
            brand_context += f"- Brand Typography: {b_font}\n"
        if b_audience:
            brand_context += f"- Target Audience: {b_audience}\n"
    elif not use_brand_kit and manual_brand:
        m_name = manual_brand.get("brand_name") or (business.get("name") if business else "")
        m_voice = manual_brand.get("brand_voice") or manual_brand.get("tone")
        m_colors = manual_brand.get("brand_colors")
        m_audience = manual_brand.get("target_audience")
        brand_parts = []
        if m_name:
            brand_parts.append(f"- Brand Name: {m_name}")
        if m_voice:
            brand_parts.append(f"- Brand Voice / Tone: {m_voice}")
        if m_colors:
            colors_repr = ", ".join(m_colors) if isinstance(m_colors, list) else str(m_colors)
            brand_parts.append(f"- Brand Color Preferences: {colors_repr}")
        if m_audience:
            brand_parts.append(f"- Target Audience: {m_audience}")
        if brand_parts:
            brand_context = "MANUAL BRANDING SETTINGS (USE_BRAND_KIT=FALSE):\n" + "\n".join(brand_parts) + "\n"

    prod_context = ""
    if product and (product.get("name") or product.get("description") or product.get("features")):
        prod_lines = ["FEATURED PRODUCT DETAILS:"]
        if product.get("name"):
            prod_lines.append(f"- Product Name: {product.get('name')}")
        if product.get("category"):
            prod_lines.append(f"- Category: {product.get('category')}")
        if product.get("description"):
            prod_lines.append(f"- Description: {product.get('description')}")
        if product.get("price") is not None and product.get("price") != "":
            price_text = f"Price: {product.get('price')}"
            if product.get("sale_price"):
                price_text += f" (Special Offer / Sale Price: {product.get('sale_price')})"
            prod_lines.append(f"- {price_text}")
        if product.get("features"):
            feats = product.get("features")
            if isinstance(feats, list):
                feat_items = "\n  * ".join(str(f) for f in feats if f)
                prod_lines.append(f"- Key Features & Highlights:\n  * {feat_items}")
            else:
                prod_lines.append(f"- Key Features & Highlights: {feats}")
        if product.get("colors") and isinstance(product.get("colors"), list):
            prod_lines.append(f"- Available Colors: {', '.join(product.get('colors'))}")
        if product.get("sizes") and isinstance(product.get("sizes"), list):
            prod_lines.append(f"- Available Sizes: {', '.join(product.get('sizes'))}")
        prod_context = "\n".join(prod_lines) + "\n"

    if products and len(products) > 1:
        prod_context += "\nALL FEATURED PRODUCTS IN CAMPAIGN:\n"
        for i, p in enumerate(products, 1):
            feat_info = f" | Features: {', '.join(p.get('features'))}" if p.get("features") else ""
            price_info = f" | Price: {p.get('price')}" if p.get("price") else ""
            prod_context += f"{i}. {p.get('name', 'Product')} ({p.get('category', 'General')}){price_info}{feat_info}\n"

    ref_note = ""
    if has_reference_images:
        subject_info = ""
        if extracted_subject:
            subject_info = f"""
IDENTIFIED REFERENCE SUBJECT: "{extracted_subject}"
KEY VISUAL TRAITS: "{extracted_traits or ''}"
"""
        ref_note = f"""
CRITICAL MANDATE FOR REFERENCE IMAGE:
The user uploaded actual product/reference images.{subject_info}
1. The entire content, headline, caption, and image_prompt MUST be directly centered on {extracted_subject or 'the exact product in the reference image'}!
2. NEVER replace or substitute {extracted_subject or 'this product/subject'} with an unrelated item or generic character.
3. The "image_prompt" MUST explicitly focus on {extracted_subject or 'the identified product'}, highlighting its authentic design, features, materials, and styling.
"""

    lang_instruction = "Write in fluent, engaging English."
    if language and language.lower() == "hinglish":
        lang_instruction = "Write in natural, trendy Hinglish (contemporary Hindi written in Roman script mixed seamlessly with English, widely used by top Indian social media creators)."
    elif language and language.lower() == "hindi":
        lang_instruction = "Write in authentic, elegant Hindi (Devanagari script)."

    subject_instruction = f"featuring {extracted_subject}" if extracted_subject else "matching the product and reference image"

    clean_content_type = (content_type or "post").lower()

    if clean_content_type in ["ad", "advertisement"]:
        type_role = "World-Class Direct-Response Advertising Copywriter & Creative Director"
        type_task = f"Create a high-converting digital advertisement campaign for {platform} optimized for objective: {objective}."
        json_template = f"""{{
    "headline": "High-impact, high-converting ad headline with compelling hook",
    "primary_text": "Persuasive direct-response ad copy emphasizing key product features, real customer benefits, and emotional resonance",
    "description": "Short, powerful secondary link description or teaser",
    "caption": "Full ad copy matching primary_text for seamless feed display",
    "call_to_action": "High-converting action phrase (e.g. Shop Now, Claim Offer, Order Today)",
    "hashtags": [
        "#relevantAdTag1",
        "#relevantAdTag2",
        "#relevantAdTag3",
        "#relevantAdTag4"
    ],
    "creative_direction": "Detailed commercial art direction for the ad visual, setting, and mood",
    "image_prompt": "Raw authentic commercial advertising photograph of {extracted_subject or product.get('name', 'the product')}, studio product photography, clean luxury commercial backdrop, 8k resolution, true-to-life textures, cinematic lighting"
}}"""
    elif clean_content_type == "caption":
        type_role = "Expert Social Media Copywriter and Engagement Specialist"
        type_task = f"Create a scroll-stopping, high-engagement social media caption for {platform} optimized for objective: {objective}."
        json_template = f"""{{
    "headline": "Catchy headline or opening hook",
    "caption": "Compelling, scroll-stopping social media caption with natural paragraph breaks, emojis, and storytelling highlighting product features, price/value, and solution",
    "call_to_action": "Engaging call to action (e.g. Link in bio, Comment below, Tap to shop)",
    "hashtags": [
        "#relevantHashtag1",
        "#relevantHashtag2",
        "#relevantHashtag3",
        "#relevantHashtag4",
        "#relevantHashtag5"
    ],
    "creative_direction": "Visual style note matching the product",
    "image_prompt": "Raw authentic photograph of {extracted_subject or product.get('name', 'the product')}, commercial photography, 8k resolution"
}}"""
    else:
        type_role = "World-Class Social Media Creative Director and AI Copywriter"
        type_task = f"Create a high-impact, scroll-stopping social media post for {platform}."
        json_template = f"""{{
    "headline": "Punchy, attention-grabbing headline with appropriate emojis",
    "caption": "Compelling, scroll-stopping social media caption with natural paragraph breaks, emojis, and storytelling highlighting key product features and benefits",
    "call_to_action": "Clear, high-converting call to action",
    "hashtags": [
        "#relevantHashtag1",
        "#relevantHashtag2",
        "#relevantHashtag3",
        "#relevantHashtag4",
        "#relevantHashtag5"
    ],
    "creative_direction": "Brief description of the visual scene and mood",
    "image_prompt": "Raw authentic 35mm photograph of {extracted_subject or product.get('name', 'authentic Indian person')}, {extracted_traits or ''}, authentic South Asian Indian facial features, natural warm wheatish Indian skin tone, dark brown eyes, realistic human skin pores and authentic textures, 8k resolution, true-to-life documentary photography, strictly no Chinese face, no East Asian face, no Caucasian face, no porcelain doll skin, no anime, no cartoon, no 3d render, no illustration, no drawing, no CGI, no watermark."
}}"""

    return f"""You are a {type_role}.
{type_task}

{biz_context}
{brand_context}
{prod_context}
MARKETING OBJECTIVE: {objective}
TARGET PLATFORM: {platform}
CONTENT TYPE: {content_type}
LANGUAGE RULE: {lang_instruction}

USER INSTRUCTION / CREATIVE PROMPT:
"{additional_instruction or f'Create an engaging {content_type} for our product.'}"
{ref_note}

Generate the complete content package. Return ONLY valid JSON in this exact structure:

{json_template}

Guidelines & Rules:
1. Make the copy lively, persuasive, and tailored to the requested mood, product, and campaign objective ({objective}).
2. Directly incorporate the product's actual name, key features, pricing/offer, and benefits into the copy.
3. Follow the brand tone and keep the copy suitable for {platform}. Make the CTA relevant and actionable.
4. Do not invent contradictory product specifications. Use only the provided product information.
5. If multiple products are provided, find a creative way to feature all of them or highlight their synergy.
6. The image_prompt must describe a single real-life, photorealistic photograph of the primary subject {subject_instruction}.
7. ETHNICITY MANDATE: When human beings, models, portraits, or festival celebrations (like Holi, Diwali, weddings, fashion) are depicted, they MUST have authentic Indian faces (natural South Asian facial features, authentic warm Indian skin tone, natural dark hair and eyes).
8. Strictly forbid any Chinese faces, East Asian facial features, Caucasian faces, porcelain doll faces, anime, cartoon, illustration, painting, 3D CGI or fantasy styling.
9. Output STRICTLY JSON without any conversational text or markdown code fence headers.
"""