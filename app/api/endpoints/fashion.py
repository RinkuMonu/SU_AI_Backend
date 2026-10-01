"""
Fashion AI Endpoints
All Fashion AI APIs - products, photoshoot, virtual try-on, history, delete.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status

from app.core.database import get_database
from app.core.security import get_current_user
from app.utils.upload import save_image
from app.ai.factory import AIProviderFactory
from app.api.dependencies import require_feature, require_credits, require_usage_limit
from app.services.subscription_service import SubscriptionService

from app.schemas.fashion import (
    FashionProductCreate,
    FashionProductResponse,
    PhotoshootGenerateRequest,
    PhotoshootGenerateResponse,
    GenerationStatusResponse,
    VirtualTryOnRequest,
    VirtualTryOnResponse,
    TryOnStatusResponse,
    GenerationHistoryResponse,
    ImageUploadResponse,
    MALE_STYLES,
    FEMALE_STYLES,
)
from app.services.fashion.photoshoot_service import (
    create_fashion_generation_job,
    run_fashion_photoshoot,
)
from app.services.fashion.tryon_service import (
    create_tryon_job,
    run_virtual_tryon,
    get_tryon_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/fashion",
    tags=["Fashion AI"],
)


# ----------------------------------------------
# HELPER
# ----------------------------------------------

def _serialize_fashion_product(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "user_id": str(doc.get("user_id", "")),
        "name": doc.get("name", ""),
        "category": doc.get("category", ""),
        "gender": doc.get("gender", ""),
        "color": doc.get("color", ""),
        "image_url": doc.get("image_url", ""),
        "processed_image_url": doc.get("processed_image_url"),
        "background_removed": doc.get("background_removed", False),
        "description": doc.get("description"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def _get_fashion_product_for_user(db, product_id: str, user_id: str) -> dict:
    """Fetch a fashion product and verify ownership."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    product = await db["fashion_products"].find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Fashion product not found")
    if str(product.get("user_id", "")) != str(user_id):
        raise HTTPException(status_code=403, detail="Not authorized to access this product")
    return product


# ----------------------------------------------
# CONFIGURATION ENDPOINT
# ----------------------------------------------

@router.get("/config", summary="Get Fashion AI configuration options")
async def get_fashion_config():
    """Returns all valid options for model styles, poses, backgrounds, etc."""
    return {
        "success": True,
        "data": {
            "categories": ["tshirt", "shirt", "dress", "hoodie", "jacket", "top", "kurti", "saree", "cotton saree", "lehenga", "other"],
            "genders": ["male", "female", "unisex"],
            "model_types": ["male", "female"],
            "model_styles": {
                "male": MALE_STYLES,
                "female": FEMALE_STYLES,
            },
            "poses": ["standing", "walking", "sitting", "hands_in_pockets", "crossed_arms", "looking_left", "looking_right", "custom"],
            "backgrounds": ["studio", "street", "cafe", "office", "home", "beach", "luxury_store", "gym", "outdoor", "custom"],
            "shot_types": ["full_body", "upper_body", "close_up"],
            "views": ["front", "back", "side"],
            "locations": ["Paris", "London", "New York", "Dubai", "Mumbai", "Delhi", "Jaipur", "Custom"],
            "virtual_tryon_configured": get_tryon_provider().is_configured(),
        }
    }


# ----------------------------------------------
# FASHION PRODUCTS
# ----------------------------------------------

@router.post(
    "/products/upload-image",
    summary="Upload a fashion product image",
    response_model=ImageUploadResponse,
)
async def upload_fashion_product_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload an image for a fashion product. Returns the image URL."""
    image_url = await save_image(file, "fashion/products")
    return {"success": True, "image_url": image_url, "message": "Fashion product image uploaded successfully"}


@router.post(
    "/products/upload-person-image",
    summary="Upload a person photo for Virtual Try-On",
    response_model=ImageUploadResponse,
)
async def upload_person_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload a person photo for Virtual Try-On. Returns the image URL."""
    image_url = await save_image(file, "fashion/tryon")
    return {"success": True, "image_url": image_url, "message": "Person photo uploaded successfully"}


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    summary="Create a fashion product",
)
async def create_fashion_product(
    data: FashionProductCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Create a new fashion product.
    The image must first be uploaded via POST /fashion/products/upload-image.
    """
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": str(current_user.get("id", "")),
        "name": data.name,
        "category": data.category,
        "gender": data.gender,
        "color": data.color,
        "image_url": data.image_url,
        "processed_image_url": None,
        "background_removed": False,
        "description": data.description,
        "created_at": now,
        "updated_at": now,
    }
    result = await db["fashion_products"].insert_one(doc)
    created = await db["fashion_products"].find_one({"_id": result.inserted_id})
    return {
        "success": True,
        "message": "Fashion product created successfully",
        "data": _serialize_fashion_product(created),
    }


@router.get(
    "/products",
    summary="List all fashion products for the current user",
)
async def list_fashion_products(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = str(current_user.get("id", ""))
    cursor = db["fashion_products"].find({"user_id": user_id}).sort("created_at", -1)
    products = []
    async for doc in cursor:
        products.append(_serialize_fashion_product(doc))
    return {"success": True, "data": products, "total": len(products)}


@router.get(
    "/products/{product_id}",
    summary="Get a specific fashion product",
)
async def get_fashion_product(
    product_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = str(current_user.get("id", ""))
    product = await _get_fashion_product_for_user(db, product_id, user_id)
    return {"success": True, "data": _serialize_fashion_product(product)}


@router.delete(
    "/products/{product_id}",
    summary="Delete a fashion product",
)
async def delete_fashion_product(
    product_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = str(current_user.get("id", ""))
    await _get_fashion_product_for_user(db, product_id, user_id)
    await db["fashion_products"].delete_one({"_id": ObjectId(product_id)})
    return {"success": True, "message": "Fashion product deleted successfully"}


# ----------------------------------------------
# AI PHOTOSHOOT
# ----------------------------------------------

@router.post(
    "/photoshoot/generate",
    response_model=PhotoshootGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start AI Fashion Photoshoot generation (async)",
    dependencies=[Depends(require_feature("ai_photoshoot")), Depends(require_credits("ai_photoshoot")), Depends(require_usage_limit("photoshoot"))]
)
async def generate_fashion_photoshoot(
    request: PhotoshootGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Start an async fashion photoshoot generation.
    Returns immediately with generation_id and status=processing.
    Poll GET /fashion/photoshoot/{generation_id}/status for results.
    """
    user_id = str(current_user.get("id", ""))

    # Validate product ownership if provided
    product_data = {}
    if request.product_id:
        product = await _get_fashion_product_for_user(db, request.product_id, user_id)
        product_data = _serialize_fashion_product(product)
    else:
        # Allow generic text-based product
        if not request.category or not request.color:
            raise HTTPException(status_code=400, detail="Must provide either product_id or both category and color")
        product_data = {
            "name": request.garment_name or f"{request.color} {request.category}",
            "category": request.category,
            "color": request.color,
            "gender": "unisex"
        }

    # Validate model_style
    valid_styles = MALE_STYLES if request.model_type == "male" else FEMALE_STYLES
    if request.model_style not in valid_styles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model_style '{request.model_style}' for {request.model_type} model. Valid: {valid_styles}"
        )

    # Validate custom fields
    if request.pose == "custom" and not request.custom_pose_description:
        raise HTTPException(status_code=400, detail="custom_pose_description is required when pose=custom")
    if request.background == "custom" and not request.custom_background_description:
        raise HTTPException(status_code=400, detail="custom_background_description is required when background=custom")

    # Deduct credits & log usage
    from app.services.credit_service import CreditService
    await CreditService.deduct_credits(db, user_id, "ai_photoshoot")
    await SubscriptionService.increment_usage(db, user_id, "photoshoot")

    # Create pending job
    generation_id = await create_fashion_generation_job(db, user_id, product_data, request)

    # Credits deducted before job creation

    # Get text generator for prompt enhancement
    text_generator = None
    try:
        text_generator = AIProviderFactory.get_provider()
    except Exception:
        pass

    # Run generation in background
    background_tasks.add_task(
        run_fashion_photoshoot,
        db=db,
        generation_id=generation_id,
        user_id=user_id,
        product=product_data,
        request=request,
        text_generator=text_generator,
    )

    return PhotoshootGenerateResponse(
        success=True,
        generation_id=generation_id,
        status="processing",
        message="Fashion photoshoot generation started. Poll status endpoint for results.",
    )


@router.get(
    "/photoshoot/{generation_id}/status",
    response_model=GenerationStatusResponse,
    summary="Check photoshoot generation status",
)
async def get_photoshoot_status(
    generation_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Poll this endpoint to check the status of a photoshoot generation."""
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail="Invalid generation_id format")

    doc = await db["fashion_generations"].find_one({"_id": ObjectId(generation_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
    if str(doc.get("user_id", "")) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this generation")

    return GenerationStatusResponse(
        success=doc.get("status") == "completed",
        generation_id=generation_id,
        status=doc.get("status", "pending"),
        images=doc.get("result_images"),
        prompt_used=doc.get("prompt_used"),
        error=doc.get("error"),
        created_at=doc.get("created_at"),
        completed_at=doc.get("completed_at"),
    )


# ----------------------------------------------
# VIRTUAL TRY-ON
# ----------------------------------------------

@router.post(
    "/virtual-tryon",
    response_model=VirtualTryOnResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start Virtual Try-On (async)",
    dependencies=[Depends(require_feature("ai_photoshoot")), Depends(require_credits("ai_photoshoot")), Depends(require_usage_limit("photoshoot"))]
)
async def start_virtual_tryon(
    request: VirtualTryOnRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Start an async virtual try-on generation.
    Person image URL must be obtained from POST /fashion/products/upload-person-image.
    
    NOTE: Virtual Try-On requires a provider to be configured.
    Check GET /fashion/config for virtual_tryon_configured status.
    """
    user_id = str(current_user.get("id", ""))

    # Validate product
    product_data = {}
    if request.product_id:
        product = await _get_fashion_product_for_user(db, request.product_id, user_id)
        product_data = _serialize_fashion_product(product)
    else:
        if not request.category or not request.color:
            raise HTTPException(status_code=400, detail="Must provide either product_id or both category and color")
        
        # Virtual Try-On requires a garment image. Generate a temporary one using Pollinations flat-lay
        import urllib.parse
        safe_prompt = urllib.parse.quote(f"{request.color} {request.category} flat lay clothing photography, white background, single item")
        garment_image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=512&height=512&nologo=true"
        
        product_data = {
            "name": request.garment_name or f"{request.color} {request.category}",
            "category": request.category,
            "color": request.color,
            "gender": "unisex",
            "image_url": garment_image_url
        }

    # Validate person image URL
    if not request.person_image_url or not request.person_image_url.startswith("/uploads/"):
        raise HTTPException(
            status_code=400,
            detail="Invalid person_image_url. Upload a person photo first via POST /fashion/products/upload-person-image"
        )

    # Deduct credits & log usage
    from app.services.credit_service import CreditService
    await CreditService.deduct_credits(db, user_id, "ai_photoshoot")
    await SubscriptionService.increment_usage(db, user_id, "photoshoot")

    # Create pending job
    job_id = await create_tryon_job(db, user_id, product_data, request.person_image_url)

    # Run in background
    background_tasks.add_task(
        run_virtual_tryon,
        db=db,
        job_id=job_id,
        user_id=user_id,
        product=product_data,
        person_image_url=request.person_image_url,
    )

    return VirtualTryOnResponse(
        success=True,
        generation_id=job_id,
        status="processing",
        message="Virtual try-on started. Poll status endpoint for results.",
    )


@router.get(
    "/virtual-tryon/{generation_id}/status",
    response_model=TryOnStatusResponse,
    summary="Check Virtual Try-On status",
)
async def get_tryon_status(
    generation_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Poll this endpoint to check the status of a virtual try-on job."""
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail="Invalid generation_id format")

    doc = await db["virtual_tryons"].find_one({"_id": ObjectId(generation_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Virtual try-on job not found")
    if str(doc.get("user_id", "")) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    return TryOnStatusResponse(
        success=doc.get("status") == "completed",
        generation_id=generation_id,
        status=doc.get("status", "pending"),
        result_image_url=doc.get("result_image_url"),
        error=doc.get("error"),
        created_at=doc.get("created_at"),
    )


# ----------------------------------------------
# HISTORY
# ----------------------------------------------

@router.get(
    "/history",
    summary="Get Fashion AI generation history",
)
async def get_fashion_history(
    type: Optional[str] = Query(None, description="Filter by type: photoshoot | tryon"),
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Returns combined history of photoshoots and virtual try-ons."""
    user_id = str(current_user.get("id", ""))
    results = []

    if type != "tryon":
        # Photoshoots
        cursor = db["fashion_generations"].find(
            {"user_id": user_id}
        ).sort("created_at", -1).skip(skip).limit(limit)

        async for doc in cursor:
            item = {
                "id": str(doc["_id"]),
                "type": "photoshoot",
                "product_id": doc.get("product_id"),
                "model_type": doc.get("model_type"),
                "model_style": doc.get("model_style"),
                "pose": doc.get("pose"),
                "background": doc.get("background"),
                "location": doc.get("location"),
                "status": doc.get("status", "pending"),
                "result_images": doc.get("result_images", []),
                "result_image_url": (doc.get("result_images") or [None])[0],
                "created_at": doc.get("created_at"),
                "completed_at": doc.get("completed_at"),
            }
            # Enrich with product name
            if item["product_id"] and ObjectId.is_valid(item["product_id"]):
                prod = await db["fashion_products"].find_one({"_id": ObjectId(item["product_id"])})
                if prod:
                    item["product_name"] = prod.get("name")
            results.append(item)

    if type != "photoshoot":
        # Virtual try-ons
        cursor = db["virtual_tryons"].find(
            {"user_id": user_id}
        ).sort("created_at", -1).skip(skip).limit(limit)

        async for doc in cursor:
            item = {
                "id": str(doc["_id"]),
                "type": "tryon",
                "product_id": doc.get("product_id"),
                "status": doc.get("status", "pending"),
                "result_image_url": doc.get("result_image_url"),
                "created_at": doc.get("created_at"),
                "completed_at": doc.get("completed_at"),
            }
            if item["product_id"] and ObjectId.is_valid(item["product_id"]):
                prod = await db["fashion_products"].find_one({"_id": ObjectId(item["product_id"])})
                if prod:
                    item["product_name"] = prod.get("name")
            results.append(item)

    # Sort combined results by created_at descending
    results.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)

    return {
        "success": True,
        "data": results,
        "total": len(results),
    }


# ----------------------------------------------
# DELETE GENERATION
# ----------------------------------------------

@router.delete(
    "/generation/{generation_id}",
    summary="Delete a fashion generation (photoshoot or tryon)",
)
async def delete_fashion_generation(
    generation_id: str,
    generation_type: str = Query(..., description="Type: photoshoot | tryon"),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail="Invalid generation_id format")

    if generation_type == "photoshoot":
        collection = db["fashion_generations"]
    elif generation_type == "tryon":
        collection = db["virtual_tryons"]
    else:
        raise HTTPException(status_code=400, detail="generation_type must be 'photoshoot' or 'tryon'")

    doc = await collection.find_one({"_id": ObjectId(generation_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
    if str(doc.get("user_id", "")) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this generation")

    await collection.delete_one({"_id": ObjectId(generation_id)})
    return {"success": True, "message": "Generation deleted successfully"}


# ----------------------------------------------
# CROSS-MODULE CONNECTIONS
# ----------------------------------------------

@router.post(
    "/generation/{generation_id}/use-for-content",
    summary="Create a social post from a fashion generation",
)
async def use_for_content(
    generation_id: str,
    generation_type: str = Query("photoshoot"),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Sends the fashion image to the Content module for caption/post generation."""
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail=f"Invalid generation_id '{generation_id}'. Must be a valid MongoDB ObjectId (24-character hex string). Get a real ID from POST /fashion/photoshoot/generate first.")

    try:
        if generation_type == "photoshoot":
            doc = await db["fashion_generations"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = (doc.get("result_images") or [None])[0] if doc else None
        elif generation_type == "tryon":
            doc = await db["virtual_tryons"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = doc.get("result_image_url") if doc else None
        else:
            raise HTTPException(status_code=400, detail="generation_type must be 'photoshoot' or 'tryon'")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
    if doc.get("status") != "completed" or not image_url:
        raise HTTPException(status_code=400, detail=f"Generation is not completed yet. Current status: {doc.get('status', 'unknown')}")

    return {
        "success": True,
        "message": "Image ready for content creation. Use the AI Content module with this image URL.",
        "data": {
            "image_url": image_url,
            "suggested_route": "/api/v1/ai/content/generate",
            "payload_hint": {"image_url": image_url, "platform": "instagram"},
        }
    }


@router.post(
    "/generation/{generation_id}/use-for-ad",
    summary="Create an ad from a fashion generation",
)
async def use_for_ad(
    generation_id: str,
    generation_type: str = Query("photoshoot"),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Returns image URL ready for the AI Ads module."""
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail=f"Invalid generation_id '{generation_id}'. Must be a valid MongoDB ObjectId (24-character hex string). Get a real ID from POST /fashion/photoshoot/generate first.")

    try:
        if generation_type == "photoshoot":
            doc = await db["fashion_generations"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = (doc.get("result_images") or [None])[0] if doc else None
        elif generation_type == "tryon":
            doc = await db["virtual_tryons"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = doc.get("result_image_url") if doc else None
        else:
            raise HTTPException(status_code=400, detail="generation_type must be 'photoshoot' or 'tryon'")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
    if doc.get("status") != "completed" or not image_url:
        raise HTTPException(status_code=400, detail=f"Generation is not completed yet. Current status: {doc.get('status', 'unknown')}")

    return {
        "success": True,
        "message": "Image ready for ad creation. Use the AI Ads module with this image URL.",
        "data": {
            "image_url": image_url,
            "suggested_route": "/api/v1/ai/ads/",
            "payload_hint": {"image_url": image_url},
        }
    }


@router.post(
    "/generation/{generation_id}/use-for-reel",
    summary="Use fashion image in a Reel",
)
async def use_for_reel(
    generation_id: str,
    generation_type: str = Query("photoshoot"),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Returns image URL ready for the Reel generation module."""
    user_id = str(current_user.get("id", ""))

    if not ObjectId.is_valid(generation_id):
        raise HTTPException(status_code=400, detail=f"Invalid generation_id '{generation_id}'. Must be a valid MongoDB ObjectId (24-character hex string). Get a real ID from POST /fashion/photoshoot/generate first.")

    try:
        if generation_type == "photoshoot":
            doc = await db["fashion_generations"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = (doc.get("result_images") or [None])[0] if doc else None
        elif generation_type == "tryon":
            doc = await db["virtual_tryons"].find_one({"_id": ObjectId(generation_id), "user_id": user_id})
            image_url = doc.get("result_image_url") if doc else None
        else:
            raise HTTPException(status_code=400, detail="generation_type must be 'photoshoot' or 'tryon'")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not doc:
        raise HTTPException(status_code=404, detail="Generation not found")
    if doc.get("status") != "completed" or not image_url:
        raise HTTPException(status_code=400, detail=f"Generation is not completed yet. Current status: {doc.get('status', 'unknown')}")

    return {
        "success": True,
        "message": "Image ready for reel creation. Use the Reel module with this image URL.",
        "data": {
            "image_url": image_url,
            "suggested_route": "/api/v1/content/generate-reel",
            "payload_hint": {"image_url": image_url},
        }
    }
