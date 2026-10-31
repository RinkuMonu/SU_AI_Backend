from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
import time
import logging
from typing import List, Optional

from app.schemas.ai import (
    SpeechToTextResponse,
    CaptionRequest,
    CaptionResponse,
    AIGenerationHistoryResponse,
    ImageGenerationRequest,
    AIGenerateRequest,
    AIGenerateResponse,
    GeminiGenerateRequest,
    GeminiGenerateResponse,
    MarketingContentPackage,
)
from app.core.config import settings
from app.services.ai_service import generate_with_openai, AIService
from app.services.gemini_service import generate_with_gemini, GeminiService
from app.models.ai import AIGenerationHistory
from app.ai.services.business_context import BusinessContextService
from app.ai.services.text_generation import TextGenerationService
from app.services.business_service import BusinessService
from app.core.security import get_current_user, get_current_user_optional
from app.services.website_analysis_service import WebsiteAnalysisService
from app.models.user import User
from app.core.database import get_database
from bson import ObjectId

from app.api.dependencies import require_feature, require_credits, require_usage_limit
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", response_model=AIGenerateResponse)
async def generate_with_ai_endpoint(
    request: AIGenerateRequest,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Centralized OpenAI generation endpoint with automatic task-based model routing:
      - task='marketing_content' or 'text': Generates marketing package via gpt-4.1-mini
      - task='video_generation' or 'video': Generates storyboard & visual script via gpt-4.1-mini
      - task='image_generation' or 'image': Generates advertisement image via gpt-image-1-mini
    """
    try:
        result = await generate_with_openai(request)
        return AIGenerateResponse(**result)
    except Exception as e:
        logger.error(f"Error in /generate endpoint: {e}")
        return AIGenerateResponse(
            success=False,
            task=request.task,
            model=request.model or "unknown",
            endpoint="/generate",
            error={"code": "GENERATION_FAILED", "message": str(e)}
        )


@router.post("/marketing-content", response_model=dict)
async def generate_marketing_content_endpoint(
    prompt: str,
    model: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Generates structured marketing content package using Gemini Function A."""
    return await generate_with_openai(task="marketing_content", prompt=prompt, model=model)


@router.post("/promotional-video", response_model=dict)
async def generate_promotional_video_endpoint(
    prompt: str,
    model: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Generates vertical 9:16 promotional video using Gemini Function B."""
    return await generate_with_openai(task="video_generation", prompt=prompt, model=model)


@router.post("/advertisement-image", response_model=dict)
async def generate_advertisement_image_endpoint(
    prompt: str,
    model: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Generates premium advertisement image using Gemini Function C."""
    return await generate_with_openai(task="image_generation", prompt=prompt, model=model)


@router.post("/generateContent", response_model=dict)
@router.post("/generate-content", response_model=dict)
async def generate_content_endpoint(
    payload: dict,
    model: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """
    Direct endpoint matching Google Gemini REST API generateContent:
    Accepts:
      - Google Gemini native format: {"contents": [{"parts": [{"text": "..."}]}]}
      - Or simple format: {"prompt": "...", "model": "gemini-3.5-flash"}
    Executes using the integrated Gemini key with trained system instructions and automatic backup key failover.
    """
    extracted_prompt = ""
    contents = payload.get("contents")
    if isinstance(contents, list) and len(contents) > 0:
        first_item = contents[0]
        if isinstance(first_item, dict):
            parts = first_item.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    extracted_prompt += part["text"] + " "
    if not extracted_prompt.strip():
        extracted_prompt = str(payload.get("prompt") or payload.get("text") or "").strip()

    if not extracted_prompt:
        raise HTTPException(status_code=400, detail="Missing required 'contents' or 'prompt' in request payload.")

    selected_model = model or payload.get("model") or getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"
    service = AIService()
    try:
        res = await service.generate_text_content(
            prompt=extracted_prompt.strip(),
            model=selected_model,
            options=payload.get("options") or {}
        )
        return {
            "success": True,
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": res["text"]}],
                        "role": "model"
                    },
                    "finishReason": "STOP"
                }
            ],
            "text": res["text"],
            "model": res["model"],
            "provider": "openai",
            "usageMetadata": res.get("usage", {})
        }
    except Exception as e:
        logger.error(f"Error in /generateContent endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    Canonical endpoint to generate realistic social media images based on prompt and optional reference images.
    Includes feature authorization, credit deduction, usage limits, and Gemini-assisted visual prompt refinement.
    """
    import os, io, re, json, random
    import httpx
    from PIL import Image
    from app.core.config import settings
    from app.ai.image.generator import ImageGenerator

    start_time = time.time()
    
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_id = str(business.id) if business else str(current_user.id)
    
    collection = await get_history_collection()
    
    history_record = AIGenerationHistory(
        user_id=str(current_user.id),
        business_id=business_id,
        generation_type="image",
        provider="openai",
        model_name=getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini"),
        input_params=request.model_dump(),
        status="processing"
    )
    
    doc = history_record.model_dump(by_alias=True, exclude={"id"})
    result = await collection.insert_one(doc)
    history_id = result.inserted_id
    
    try:
        extracted_subject = None
        extracted_traits = None
        pil_refs = []

        # 1. If reference images provided, extract subject using OpenAI Multimodal Vision (gpt-4.1-mini)
        if request.reference_images and getattr(settings, "OPENAI_API_KEY", None):
            try:
                from app.ai.factory import AIProviderFactory
                provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
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
                        async with httpx.AsyncClient(timeout=10.0, headers=headers) as h_c:
                            res = await h_c.get(clean_ref, follow_redirects=True)
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
                    v_res = await provider.generate_text(
                        prompt=vision_prompt,
                        images=pil_refs,
                        system_prompt="You are a multimodal vision analyst. Return ONLY valid JSON."
                    )
                    v_text = (v_res.get("text", "") if isinstance(v_res, dict) else str(v_res)).strip()
                    if v_text:
                        v_clean = v_text.replace("```json", "").replace("```", "")
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
        img_res = await image_gen.generate(prompt=final_prompt, aspect_ratio="1:1", seed=seed, pil_refs=pil_refs)
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


@router.post("/competitor-analysis", response_model=dict, dependencies=[Depends(require_feature("analytics"))])
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
    current_user=Depends(get_current_user_optional),
    db=Depends(get_database)
):
    """
    Directly crawls, scrapes, and analyzes the target website URL for dynamic onboarding.
    Extracts authentic photos/images, CSS colors, brand voice, and business metadata.
    """
    user_id = None
    if current_user:
        user_id = str(current_user.id if hasattr(current_user, "id") else (current_user.get("id") or current_user.get("_id")))

    target_url = request.get_url()
    if target_url:
        result = await WebsiteAnalysisService.analyze_website_direct(
            db=db,
            url=target_url,
            user_id=user_id,
            primary_goal=request.primary_goal,
            target_audience=request.target_audience
        )
        return {
            "success": True,
            "message": "Website analysis completed successfully",
            "data": result
        }

    # Fallback to CRO audit if no URL provided
    uid = user_id or "anonymous"
    result = await MarketingIntelligenceService.analyze_website(db, uid, request)
    return {
        "success": True,
        "message": "Website audit completed successfully",
        "data": result.model_dump()
    }


@router.post("/trend-analysis", response_model=dict, dependencies=[Depends(require_feature("content_calendar"))])
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


@router.post("/product-marketing", response_model=dict, dependencies=[Depends(require_feature("ai_post"))])
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


@router.post("/brand-strategy", response_model=dict, dependencies=[Depends(require_feature("ai_caption"))])
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






@router.post("/speech-to-text", response_model=SpeechToTextResponse)
@router.post("/stt", response_model=SpeechToTextResponse, include_in_schema=False)
async def speech_to_text_endpoint(
    file: UploadFile = File(..., description="Audio recording file (webm, wav, mp3, m4a, ogg, flac, etc.)"),
    language: Optional[str] = Form(None, description="Optional language code (e.g. 'en', 'hi', 'hi-en', 'auto')"),
    prompt: Optional[str] = Form(None, description="Optional transcription hint or vocabulary"),
    settings: Optional[str] = Form(None, description="Optional transcription settings JSON string"),
    current_user=Depends(get_current_user),
):
    """
    Optional Speech-to-Text transcription fallback endpoint for DhandaGrow.
    Provides backend transcription when browser-native speech recognition is unsupported.
    Transcribes spoken words verbatim without generating captions, summaries, or AI content.
    Supports English, Hindi, and Hinglish.
    """
    import json
    from app.services.stt_service import STTService

    settings_dict = None
    if settings:
        try:
            settings_dict = json.loads(settings)
        except Exception:
            pass

    return await STTService.transcribe_audio(
        file=file,
        language=language,
        prompt=prompt,
        settings_dict=settings_dict
    )
