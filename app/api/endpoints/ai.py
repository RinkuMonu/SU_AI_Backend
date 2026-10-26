from fastapi import APIRouter, Depends, HTTPException, status
import time
from typing import List

from app.schemas.ai import CaptionRequest, CaptionResponse, AIGenerationHistoryResponse, ImageGenerationRequest
from app.models.ai import AIGenerationHistory
from app.ai.services.business_context import BusinessContextService
from app.ai.services.text_generation import TextGenerationService
from app.services.business_service import BusinessService
from app.core.security import get_current_user
from app.models.user import User
from app.core.database import get_database
from bson import ObjectId

from app.api.dependencies import require_feature, require_credits, require_usage_limit
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService

router = APIRouter()
async def get_history_collection():
    db = get_database()
    return db["ai_generations"]

@router.get("/context", response_model=dict)
async def get_ai_context(current_user: User = Depends(get_current_user)):
    """
    Retrieves the comprehensive business context for the current user's business.
    """
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_id = str(business.id) if business else str(current_user.id)

    context = await BusinessContextService.get_business_context(business_id)
    return context

@router.post("/caption", response_model=dict, dependencies=[Depends(require_feature("ai_caption")), Depends(require_credits("ai_caption")), Depends(require_usage_limit("post"))])
async def generate_caption(request: CaptionRequest, current_user: User = Depends(get_current_user)):
    """
    Generates a social media caption based on business context and product.
    """
    start_time = time.time()
    
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_id = str(business.id) if business else str(current_user.id)

    collection = await get_history_collection()
    
    # 1. Prepare initial history record
    history_record = AIGenerationHistory(
        user_id=str(current_user.id),
        business_id=business_id,
        generation_type="caption",
        provider="mock", # This would be fetched from settings ideally
        model_name="mock-model-v1",
        input_params=request.model_dump(),
        status="processing"
    )
    
    doc = history_record.model_dump(by_alias=True, exclude={"id"})
    result = await collection.insert_one(doc)
    history_id = result.inserted_id

    try:
        # 2. Get Context
        context = await BusinessContextService.get_business_context(business_id)
        
        # 3. Generate content
        caption_response, metadata = await TextGenerationService.generate_caption(
            context=context,
            product_id=request.product_id,
            objective=request.objective,
            tone=request.tone,
            language=request.language,
            offer=request.offer,
            cta=request.cta
        )
        
        # 4. Update history with success
        execution_time = int((time.time() - start_time) * 1000)
        await collection.update_one(
            {"_id": history_id},
            {"$set": {
                "status": "success",
                "output_data": caption_response.model_dump(),
                "execution_time_ms": execution_time,
                "provider": metadata.get("provider", "unknown"),
                "model_name": metadata.get("model", "unknown")
            }}
        )
        
        # Deduct credits & log usage
        db = get_database()
        await CreditService.deduct_credits(db, str(current_user.id), "ai_caption")
        await SubscriptionService.increment_usage(db, str(current_user.id), "post")

        
        return {
            "success": True,
            "message": "Caption generated successfully",
            "data": caption_response.model_dump()
        }

    except Exception as e:
        # Update history with failure
        execution_time = int((time.time() - start_time) * 1000)
        await collection.update_one(
            {"_id": history_id},
            {"$set": {
                "status": "failed",
                "error_message": str(e),
                "execution_time_ms": execution_time
            }}
        )
        # Safe error masking for clients as requested in prompt (Sec 14)
        return {
            "success": False,
            "message": "AI generation failed. Please try again.",
            "error": {
                "code": "AI_GENERATION_FAILED"
            }
        }

@router.post("/image", response_model=dict, dependencies=[Depends(require_feature("ai_image")), Depends(require_credits("ai_image")), Depends(require_usage_limit("image"))])
async def generate_image(request: ImageGenerationRequest, current_user: User = Depends(get_current_user)):
    """
    Generates an image based on the provided prompt and optional reference images.
    """
    start_time = time.time()
    
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_id = str(business.id) if business else str(current_user.id)
    
    collection = await get_history_collection()
    
    history_record = AIGenerationHistory(
        user_id=str(current_user.id),
        business_id=business_id,
        generation_type="image",
        provider="mock",
        model_name="mock-model-v1",
        input_params=request.model_dump(),
        status="processing"
    )
    
    doc = history_record.model_dump(by_alias=True, exclude={"id"})
    result = await collection.insert_one(doc)
    history_id = result.inserted_id
    
    try:
        from app.ai.image.generator import ImageGenerator
        from app.core.config import settings
        
        image_gen = ImageGenerator(
            api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
            api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
        )
        
        # Determine the primary reference image if multiple were uploaded
        primary_ref = None
        if request.reference_images and len(request.reference_images) > 0:
            primary_ref = request.reference_images[0]
            
        img_res = await image_gen.generate(prompt=request.prompt, product_image=primary_ref)
        image_url = img_res.get("image_url", "")
        
        if not image_url:
            raise Exception("No image generated")
            
        execution_time = int((time.time() - start_time) * 1000)
        await collection.update_one(
            {"_id": history_id},
            {"$set": {
                "status": "success",
                "output_data": {"image_url": image_url},
                "execution_time_ms": execution_time
            }}
        )
        
        db = get_database()
        await CreditService.deduct_credits(db, str(current_user.id), "ai_image")
        await SubscriptionService.increment_usage(db, str(current_user.id), "image")
        
        return {
            "success": True,
            "message": "Image generated successfully",
            "data": {"image_url": image_url}
        }
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        await collection.update_one(
            {"_id": history_id},
            {"$set": {
                "status": "failed",
                "error_message": str(e),
                "execution_time_ms": execution_time
            }}
        )
        return {
            "success": False,
            "message": "AI image generation failed. Please try again.",
            "error": {"code": "AI_GENERATION_FAILED", "details": str(e)}
        }

@router.get("/generations", response_model=List[dict])
async def get_generations(skip: int = 0, limit: int = 20, current_user: User = Depends(get_current_user)):
    """
    Retrieves the AI generation history for the current user.
    """
    collection = await get_history_collection()
    cursor = collection.find({"user_id": str(current_user.id)}).sort("created_at", -1).skip(skip).limit(limit)
    
    results = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        # Datetime serialization fix
        if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
            doc["created_at"] = doc["created_at"].isoformat()
        if "updated_at" in doc and hasattr(doc["updated_at"], "isoformat"):
            doc["updated_at"] = doc["updated_at"].isoformat()
        results.append(doc)
        
    return results

@router.get("/generations/{generation_id}", response_model=dict)
async def get_generation_by_id(generation_id: str, current_user: User = Depends(get_current_user)):
    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")
        
    collection = await get_history_collection()
    doc = await collection.find_one({"_id": ObjectId(generation_id), "user_id": str(current_user.id)})
    
    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
        
    doc["id"] = str(doc.pop("_id"))
    if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
        doc["created_at"] = doc["created_at"].isoformat()
    if "updated_at" in doc and hasattr(doc["updated_at"], "isoformat"):
        doc["updated_at"] = doc["updated_at"].isoformat()
        
    return doc


@router.post("/image", response_model=dict)
async def generate_image_endpoint(request: ImageGenerationRequest, current_user: User = Depends(get_current_user)):
    """
    Generates a realistic social media image matching prompt and any uploaded reference images.
    """
    import os, io, re, json, random
    import httpx
    from PIL import Image
    from app.core.config import settings
    from app.ai.image.generator import ImageGenerator

    extracted_subject = None
    extracted_traits = None
    pil_refs = []

    # 1. If reference images provided, extract subject using Gemini Vision
    if request.reference_images and settings.GEMINI_API_KEY:
        try:
            import google.genai as genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            for img_ref in request.reference_images[:3]:
                if not img_ref or not isinstance(img_ref, str):
                    continue
                clean_ref = img_ref.strip()
                if "uploads/" in clean_ref:
                    rel_part = clean_ref.split("uploads/")[-1].split("?")[0]
                    local_path = os.path.join(os.getcwd(), "uploads", rel_part)
                    if os.path.exists(local_path):
                        img = Image.open(local_path).convert("RGB")
                        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                        pil_refs.append(img)
                        continue
                if clean_ref.startswith("http://") or clean_ref.startswith("https://"):
                    headers = {"User-Agent": "Mozilla/5.0"}
                    async with httpx.AsyncClient(timeout=10.0, headers=headers) as c:
                        res = await c.get(clean_ref, follow_redirects=True)
                        if res.status_code == 200 and len(res.content) > 1000:
                            img = Image.open(io.BytesIO(res.content)).convert("RGB")
                            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                            pil_refs.append(img)

            if pil_refs:
                vision_prompt = (
                    "Examine this reference image with extreme visual precision.\n"
                    "Identify:\n"
                    "1. Exact Primary Subject (exact name if historical figure, deity, celebrity, or exact product type/garment/item):\n"
                    "2. Key visual traits (clothing, face, glasses, distinctive colors, textures):\n"
                    "Return ONLY a JSON object: {\"subject_name\": \"...\", \"key_traits\": \"...\"}"
                )
                v_res = client.models.generate_content(
                    model=getattr(settings, "GEMINI_FAST_MODEL", None) or getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=[*pil_refs, vision_prompt]
                )
                if v_res and v_res.text:
                    v_clean = v_res.text.strip().replace("```json", "").replace("```", "")
                    v_match = re.search(r'\{.*\}', v_clean, re.DOTALL)
                    if v_match:
                        v_json = json.loads(v_match.group(0))
                        extracted_subject = v_json.get("subject_name")
                        extracted_traits = v_json.get("key_traits")
        except Exception:
            pass

    # 2. Formulate realistic photorealistic prompt anchored on subject & authentic Indian features
    base_prompt = request.prompt or request.additional_instruction or "high quality social media photography"
    human_terms = ["woman", "women", "girl", "girls", "man", "men", "boy", "person", "people", "portrait", "face", "model", "holi", "diwali", "festiv", "saree", "lehenga", "ethnic"]
    is_human = any(k in base_prompt.lower() for k in human_terms)
    indian_clause = "authentic Indian person, natural South Asian facial features, warm wheatish Indian skin tone, dark brown eyes, strictly no Chinese face, no East Asian face, no porcelain doll face, no anime, " if is_human else ""

    if extracted_subject:
        if extracted_subject.lower() not in base_prompt.lower():
            final_prompt = (
                f"Raw authentic photograph of {extracted_subject}, {extracted_traits or ''}, "
                f"{indian_clause}{base_prompt}, cinematic natural lighting, photorealistic skin and fabric textures, 8k resolution, authentic likeness, documentary photography"
            )
        else:
            final_prompt = f"Raw authentic photograph of {indian_clause}{base_prompt}, 8k resolution, natural lighting, documentary photography"
    else:
        final_prompt = f"Raw authentic photograph of {indian_clause}{base_prompt}, 8k resolution, natural lighting, documentary photography"

    # 3. Generate image
    image_gen = ImageGenerator()
    seed = random.randint(1000, 999999)
    res = await image_gen.generate(prompt=final_prompt, aspect_ratio="1:1", seed=seed, pil_refs=pil_refs)

    return {
        "success": True,
        "data": {
            "image_url": res.get("image_url", "")
        }
    }


# ============================================================================
# Advanced Marketing & Competitive Intelligence Endpoints
# ============================================================================

from app.services.marketing_intelligence_service import MarketingIntelligenceService
from app.schemas.ai import (
    CompetitorAnalysisRequest,
    CompetitorAnalysisResponse,
    WebsiteAnalysisRequest,
    WebsiteAnalysisResponse,
    SocialTrendAnalysisRequest,
    SocialTrendAnalysisResponse,
    ProductMarketingRequest,
    ProductMarketingResponse,
    BrandStrategyRequest,
    BrandStrategyResponse,
)


@router.post("/competitor-analysis", response_model=dict)
async def analyze_competitors_endpoint(
    request: CompetitorAnalysisRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Analyzes competitive landscape, competitor strengths/weaknesses, and strategic differentiators
    grounded in verified business context.
    """
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    result = await MarketingIntelligenceService.analyze_competitors(db, user_id, request)
    return {
        "success": True,
        "message": "Competitor analysis completed successfully",
        "data": result.model_dump()
    }


@router.post("/website-analysis", response_model=dict)
async def analyze_website_endpoint(
    request: WebsiteAnalysisRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Conducts an AI audit of conversion funnels, brand clarity, and SEO opportunities for the user's web storefront.
    """
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    result = await MarketingIntelligenceService.analyze_website(db, user_id, request)
    return {
        "success": True,
        "message": "Website analysis completed successfully",
        "data": result.model_dump()
    }


@router.post("/trend-analysis", response_model=dict)
async def analyze_social_trends_endpoint(
    request: SocialTrendAnalysisRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Extracts viral social media trends, high-converting hooks, audio recommendations, and content calendar ideas.
    """
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    result = await MarketingIntelligenceService.analyze_social_trends(db, user_id, request)
    return {
        "success": True,
        "message": "Social media trend analysis completed successfully",
        "data": result.model_dump()
    }


@router.post("/product-marketing", response_model=dict)
async def generate_product_marketing_endpoint(
    request: ProductMarketingRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Derives unique selling propositions, target buyer personas, and multi-channel marketing copy directly from product specs.
    """
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    result = await MarketingIntelligenceService.generate_product_marketing(db, user_id, request)
    return {
        "success": True,
        "message": "Product marketing strategy generated successfully",
        "data": result.model_dump()
    }


@router.post("/brand-strategy", response_model=dict)
async def generate_brand_strategy_endpoint(
    request: BrandStrategyRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Develops comprehensive brand voice guidelines, color psychology, and content pillars anchored in the saved Brand Kit.
    """
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    result = await MarketingIntelligenceService.generate_brand_strategy(db, user_id, request)
    return {
        "success": True,
        "message": "Brand strategy generated successfully",
        "data": result.model_dump()
    }




