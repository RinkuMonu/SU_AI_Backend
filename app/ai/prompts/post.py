def build_post_prompt(
    business: dict,
    brand: dict,
    product: dict,
    platform: str,
    objective: str,
    language: str,
    additional_instruction: str | None = None,
    has_reference_images: bool = False,
    extracted_subject: str | None = None,
    extracted_traits: str | None = None,
) -> str:
    biz_context = ""
    # Only include business info if explicitly relevant or product is specified
    if business and business.get("name") and product:
        biz_context = f"""BUSINESS DETAILS:
- Name: {business.get('name', 'Our Brand')}
- Industry: {business.get('industry', 'Retail')}
- Description: {business.get('description', '')}
"""

    brand_context = ""
    if brand and any(brand.values()) and product:
        brand_context = f"""BRAND GUIDELINES:
- Voice/Tone: {brand.get('voice', 'Inspiring, authentic, premium')}
"""

    prod_context = ""
    if product and (product.get("name") or product.get("description")):
        prod_context = f"""FEATURED PRODUCT:
- Name: {product.get('name', '')}
- Category: {product.get('category', '')}
- Description: {product.get('description', '')}
- Price: {product.get('price', '')}
"""

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
The user uploaded a reference image.{subject_info}
1. The entire post, headline, caption, and image_prompt MUST be directly centered on {extracted_subject or 'the exact subject in the reference image'}!
2. NEVER replace or substitute {extracted_subject or 'this subject'} with an unrelated model or generic character.
3. The "image_prompt" MUST explicitly focus on {extracted_subject or 'the identified subject'}, capturing their exact likeness, attire, styling, and distinctive traits.
"""

    lang_instruction = "Write in fluent, engaging English."
    if language.lower() == "hinglish":
        lang_instruction = "Write in natural, trendy Hinglish (contemporary Hindi written in Roman script mixed seamlessly with English, widely used by top Indian social media creators)."
    elif language.lower() == "hindi":
        lang_instruction = "Write in authentic, elegant Hindi (Devanagari script)."

    subject_instruction = f"featuring {extracted_subject}" if extracted_subject else "matching the prompt and reference image"

    return f"""You are a world-class Social Media Creative Director and AI Copywriter.
Create a high-impact, scroll-stopping social media post for {platform}.

{biz_context}
{brand_context}
{prod_context}
MARKETING OBJECTIVE: {objective}
TARGET PLATFORM: {platform}
LANGUAGE RULE: {lang_instruction}

USER INSTRUCTION / CREATIVE PROMPT:
"{additional_instruction or 'Create an engaging commercial post for our brand.'}"
{ref_note}

Generate the complete post package. Return ONLY valid JSON in this exact structure:

{{
    "headline": "Punchy, attention-grabbing headline with appropriate emojis",
    "caption": "Compelling, scroll-stopping social media caption with natural paragraph breaks, emojis, and storytelling",
    "call_to_action": "Clear, high-converting call to action",
    "hashtags": [
        "#relevantHashtag1",
        "#relevantHashtag2",
        "#relevantHashtag3",
        "#relevantHashtag4",
        "#relevantHashtag5"
    ],
    "creative_direction": "Brief description of the visual scene and mood",
    "image_prompt": "Raw authentic 35mm photograph of {extracted_subject or 'authentic Indian person'}, {extracted_traits or ''}, authentic South Asian Indian facial features, natural warm wheatish Indian skin tone, dark brown eyes, realistic human skin pores and authentic textures, 8k resolution, true-to-life documentary photography, strictly no Chinese face, no East Asian face, no Caucasian face, no porcelain doll skin, no anime, no cartoon, no 3d render, no illustration, no drawing, no CGI, no watermark."
}}

Guidelines:
1. Make the caption lively, persuasive, and tailored to the requested mood and subject.
2. The image_prompt must describe a single real-life, photorealistic photograph of the primary subject {subject_instruction}.
3. ETHNICITY MANDATE: When human beings, models, portraits, or festival celebrations (like Holi, Diwali, weddings, fashion) are depicted, they MUST have authentic Indian faces (natural South Asian facial features, authentic warm Indian skin tone, natural dark hair and eyes).
4. Strictly forbid any Chinese faces, East Asian facial features, Caucasian faces, porcelain doll faces, anime, cartoon, illustration, painting, 3D CGI or fantasy styling.
5. Output STRICTLY JSON without any conversational text or markdown code fence headers.
"""