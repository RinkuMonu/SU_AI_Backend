def build_ad_prompt(
    product: dict,
    prompt: str | None = None,
    platform: str | None = None,
    objective: str | None = None,
    language: str | None = None,
    target_audience: str | None = None,
    cta: str | None = None,
    additional_instruction: str | None = None,
):
    user_prompt = prompt or additional_instruction or ""
    
    return f"""
Create a high-converting digital advertisement based on the user's prompt.

PRODUCT
Name: {product.get("name", "")}
Description: {product.get("description", "")}
Price: {product.get("price", "")}

USER PROMPT (Instructions for Ad):
{user_prompt}

Return JSON with:

{{
  "headline": "...",
  "primary_text": "...",
  "description": "...",
  "cta": "...",
  "hashtags": ["...", "...", "..."]
}}

Rules:
- Keep product claims accurate based on the prompt.
- Ensure the output strictly follows the JSON format.
"""
