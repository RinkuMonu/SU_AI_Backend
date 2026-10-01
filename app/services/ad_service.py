from app.ai.prompts.ad import build_ad_prompt


async def generate_ad(
    db,
    user_id: str,
    product: dict,
    request,
    text_generator,
    image_generator,
):

    prompt = build_ad_prompt(
        product=product,
        prompt=getattr(request, 'prompt', None),
        platform=getattr(request, 'platform', None),
        objective=getattr(request, 'objective', None),
        language=getattr(request, 'language', None),
        target_audience=getattr(request, 'target_audience', None),
        cta=getattr(request, 'cta', None),
        additional_instruction=getattr(request, 'additional_instruction', None),
    )

    # Generate ad copy
    try:
        copy_result = await text_generator.generate_json(
            prompt=prompt
        )
    except Exception as e:
        print(f"Ad copy generation failed: {e}")
        copy_result = {
            "headline": f"Discover {product.get('name', 'Our Product')}",
            "primary_text": "Experience the best quality. Upgrade your lifestyle today with our latest collection.",
            "description": "Perfect for your needs, designed for excellence.",
            "cta": request.cta or "Shop Now",
            "hashtags": ["#quality", "#premium", "#newarrival"]
        }

    # Generate creative
    creative_prompt = f"""
Create an advertising creative for:

Product:
{product.get("name", "")}

Platform:
{request.platform}

Objective:
{request.objective}

Headline:
{copy_result.get("headline", "")}

Style:
Professional commercial advertising.
Suitable for {request.platform}.
"""

    image_result = await image_generator.generate(
        prompt=creative_prompt,
        product_image=product.get("image_url"),
    )

    result = {
        "headline": copy_result.get("headline"),
        "primary_text": copy_result.get("primary_text"),
        "description": copy_result.get("description"),
        "cta": copy_result.get("cta"),
        "hashtags": copy_result.get("hashtags", []),
        "creative_url": image_result.get("image_url"),
    }

    ad_document = {
        "user_id": user_id,
        "product_id": request.product_id,
        "prompt": getattr(request, 'prompt', None),
        "platform": getattr(request, 'platform', None),
        "objective": getattr(request, 'objective', None),
        "language": getattr(request, 'language', None),
        "target_audience": getattr(request, 'target_audience', None),
        "headline": result["headline"],
        "primary_text": result["primary_text"],
        "description": result["description"],
        "cta": result["cta"],
        "hashtags": result["hashtags"],
        "creative_url": result["creative_url"],
        "status": "generated",
    }

    inserted = await db.ads.insert_one(ad_document)

    # Save to Content Library
    await db.contents.insert_one({
        "user_id": user_id,
        "type": "ad",
        "source_id": str(inserted.inserted_id),
        "product_id": request.product_id,
        "title": result["headline"],
        "media_url": result["creative_url"],
        "caption": result["primary_text"],
        "platform": getattr(request, 'platform', None),
        "status": "generated",
    })

    result["id"] = str(inserted.inserted_id)

    return result
