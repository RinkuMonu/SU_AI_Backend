def build_post_prompt(
    business: dict,
    brand: dict,
    product: dict,
    products: list,
    platform: str,
    objective: str,
    language: str,
    additional_instruction: str | None = None,
) -> str:

    return f"""
You are an AI marketing assistant for a business.

BUSINESS INFORMATION:
{business}

BRAND KIT:
{brand}

PRODUCT(S) INFORMATION:
Primary Product: {product}
All Selected Products: {products if products else [product]}

TARGET PLATFORM:
{platform}

MARKETING OBJECTIVE:
{objective}

LANGUAGE:
{language}

ADDITIONAL INSTRUCTION:
{additional_instruction or "None"}

Create a marketing post for this product.

Return ONLY valid JSON in this structure:

{{
    "headline": "short attention grabbing headline",
    "caption": "engaging social media caption",
    "call_to_action": "clear CTA",
    "hashtags": [
        "#hashtag1",
        "#hashtag2",
        "#hashtag3"
    ],
    "creative_direction": "short description of recommended visual"
}}

Rules:

1. Do not invent product specifications.
2. Use only the provided product(s) information.
3. If multiple products are provided, find a creative way to feature all of them or focus on their relationship.
3. Follow the brand tone.
4. Keep the caption suitable for the selected platform.
5. Make the CTA relevant.
6. Do not mention information that does not exist in the product data.
"""