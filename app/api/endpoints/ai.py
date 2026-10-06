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


@router.post("/image", response_model=dict, dependencies=[Depends(require_feature("ai_post")), Depends(require_credits("ai_post")), Depends(require_usage_limit("post"))])
async def generate_image(request: ImageGenerationRequest, current_user: User = Depends(get_current_user)):
    db = get_database()
    
    start_time = time.time()
    
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_id = str(business.id) if business else str(current_user.id)

    collection = await get_history_collection()
    
    history_record = AIGenerationHistory(
        user_id=str(current_user.id),
        business_id=business_id,
        generation_type="image",
        provider="pollinations", 
        model_name="stable-diffusion",
        input_params=request.model_dump(),
        status="processing"
    )
    
    doc = history_record.model_dump(by_alias=True, exclude={"id"})
    result = await collection.insert_one(doc)
    history_id = result.inserted_id

    try:
        from app.ai.image.generator import ImageGenerator
        from app.core.config import settings
        
        image_generator = ImageGenerator(
            api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
            api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
        )

        prompt = request.prompt
        if request.additional_instruction:
            prompt += f" {request.additional_instruction}"

        product_image_url = None
        if request.product_id:
            from bson import ObjectId
            if ObjectId.is_valid(request.product_id):
                prod = await db["products"].find_one({"_id": ObjectId(request.product_id), "business_id": ObjectId(business_id)})
                if prod and prod.get("image_url"):
                    product_image_url = prod["image_url"]

        response = await image_generator.generate(
            prompt=prompt,
            product_image=product_image_url
        )
        
        execution_time = int((time.time() - start_time) * 1000)
        await collection.update_one(
            {"_id": history_id},
            {"$set": {
                "status": "success",
                "output_data": response,
                "execution_time_ms": execution_time,
                "provider": "pollinations",
                "model_name": "stable-diffusion"
            }}
        )
        
        await CreditService.deduct_credits(db, str(current_user.id), "ai_post")
        await SubscriptionService.increment_usage(db, str(current_user.id), "post")

        return {
            "success": True,
            "message": "Image generated successfully",
            "data": response
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
            "message": "AI generation failed. Please try again.",
            "error": {
                "code": "AI_GENERATION_FAILED"
            }
        }
