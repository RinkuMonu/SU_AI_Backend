import os
import uuid
import re
from typing import Optional, List
from pathlib import Path
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.core.categories import (
    get_all_categories,
    get_subcategories,
    search_categories,
    get_preset_products
)
from app.schemas.reel import (
    GenerateReelRequest,
    ReelGenerationResponse,
    ReelJobStatus,
    EnhanceImageRequest,
    EnhanceImageResponse
)
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products, serialize_product
from app.services.reel_service import ReelService
from app.services.image_enhancement_service import ImageEnhancementService
from app.api.dependencies import require_feature, require_credits, require_usage_limit
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService

# Primary router mounted under /api/v1/content for existing integration compatibility
router = APIRouter(
    prefix="/api/v1/content",
    tags=["Reels"]
)

# Alias router for direct /api/v1/reels path
reels_router = APIRouter(
    prefix="/api/v1/reels",
    tags=["Reels"]
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/m4a", "audio/x-m4a", "audio/aac"}
MAX_IMAGE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


# ============================================================================
# 1. CATEGORY & PRODUCT TAXONOMY ENDPOINTS
# ============================================================================

@router.get("/reels/categories")
@reels_router.get("/categories")
async def get_categories_endpoint(q: Optional[str] = None):
    """Returns structured product categories and subcategories with keyword search."""
    if q:
        return {"success": True, "data": search_categories(q)}
    return {"success": True, "data": get_all_categories()}


@router.get("/reels/subcategories")
@reels_router.get("/subcategories")
async def get_subcategories_endpoint(category_id: Optional[str] = None):
    """Returns subcategories, optionally filtered by category_id."""
    data = get_subcategories(category_id)
    return {"success": True, "category_id": category_id, "data": data}


@router.get("/reels/products/search")
@reels_router.get("/products/search")
async def search_products_endpoint(
    q: str = Query(..., description="Search keyword for products"),
    current_user = Depends(get_current_user)
):
    """Searches user catalogue, fashion inventory, and product presets by keyword."""
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    results = []

    clean_q = q.strip()
    if clean_q and business and ObjectId.is_valid(str(business.id)):
        # 1. Search user's own product catalogue
        cursor = db["products"].find({
            "business_id": ObjectId(str(business.id)),
            "$or": [
                {"name": {"$regex": clean_q, "$options": "i"}},
                {"description": {"$regex": clean_q, "$options": "i"}},
                {"product_id": {"$regex": clean_q, "$options": "i"}}
            ]
        }).limit(20)
        async for doc in cursor:
            p = serialize_product(doc)
            p["source"] = "user_catalogue"
            results.append(p)

        # 2. Search fashion products if applicable
        fcursor = db["fashion_products"].find({
            "$or": [
                {"name": {"$regex": clean_q, "$options": "i"}},
                {"description": {"$regex": clean_q, "$options": "i"}}
            ]
        }).limit(10)
        async for fdoc in fcursor:
            results.append({
                "id": str(fdoc["_id"]),
                "name": fdoc.get("name"),
                "category": fdoc.get("category", "Fashion & Apparel"),
                "description": fdoc.get("description", ""),
                "price": fdoc.get("price", 0),
                "image_url": fdoc.get("image_url"),
                "images": [fdoc.get("image_url")] if fdoc.get("image_url") else [],
                "source": "fashion_catalogue"
            })

    # 3. Include category taxonomy presets
    presets = get_preset_products(query=clean_q)
    for pr in presets:
        pr_copy = dict(pr)
        pr_copy["source"] = "preset_catalogue"
        results.append(pr_copy)

    return {"success": True, "query": clean_q, "count": len(results), "data": results}


@router.get("/reels/products")
@reels_router.get("/products")
async def get_products_by_category_endpoint(
    category_id: Optional[str] = None,
    current_user = Depends(get_current_user)
):
    """Returns products for a given category from user catalogue and presets."""
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    results = []

    if business and ObjectId.is_valid(str(business.id)):
        query_filter = {"business_id": ObjectId(str(business.id))}
        if category_id:
            query_filter["$or"] = [
                {"category": {"$regex": f"^{re.escape(category_id)}$", "$options": "i"}},
                {"category_id": category_id}
            ]
        cursor = db["products"].find(query_filter).limit(50)
        async for doc in cursor:
            p = serialize_product(doc)
            p["source"] = "user_catalogue"
            results.append(p)

    # Add relevant preset products
    presets = get_preset_products(category_id=category_id)
    for pr in presets:
        pr_copy = dict(pr)
        pr_copy["source"] = "preset_catalogue"
        results.append(pr_copy)

    return {"success": True, "category_id": category_id, "count": len(results), "data": results}


# ============================================================================
# 2. FILE UPLOAD ENDPOINTS (IMAGE & AUDIO)
# ============================================================================

@router.post("/upload-image")
@router.post("/reels/upload-image")
@reels_router.post("/upload-image")
async def upload_product_image_endpoint(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    """Securely uploads and stores an authentic raw product image for reel generation."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image format '{file.content_type}'. Supported: JPEG, PNG, WebP."
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Image size exceeds maximum limit of 15MB.")

    if len(content) < 500:
        raise HTTPException(status_code=400, detail="Invalid or empty image file.")

    ext = Path(file.filename or "image.jpg").suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    dest_dir = Path("uploads") / "products"
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"raw_{uuid.uuid4().hex[:12]}{ext}"
    dest_path = dest_dir / filename

    with open(dest_path, "wb") as f:
        f.write(content)

    public_url = settings.get_public_url(f"/uploads/products/{filename}")
    return {
        "success": True,
        "image_id": filename,
        "image_url": public_url,
        "filename": filename,
        "size_bytes": len(content),
        "content_type": file.content_type
    }


@router.post("/upload-audio")
@router.post("/reels/upload-audio")
@reels_router.post("/upload-audio")
async def upload_audio_endpoint(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    """Securely uploads and validates a user-provided narration/voiceover audio track."""
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid audio format '{file.content_type}'. Supported: MP3, WAV, M4A, OGG."
        )

    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Audio size exceeds maximum limit of 25MB.")

    if len(content) < 1000:
        raise HTTPException(status_code=400, detail="Invalid or empty audio file.")

    ext = Path(file.filename or "audio.mp3").suffix.lower()
    if ext not in [".mp3", ".wav", ".m4a", ".ogg"]:
        ext = ".mp3"

    dest_dir = Path("uploads") / "audio"
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"user_{uuid.uuid4().hex[:12]}{ext}"
    dest_path = dest_dir / filename

    with open(dest_path, "wb") as f:
        f.write(content)

    public_url = settings.get_public_url(f"/uploads/audio/{filename}")
    return {
        "success": True,
        "audio_id": filename,
        "audio_url": public_url,
        "filename": filename,
        "size_bytes": len(content),
        "content_type": file.content_type
    }


# ============================================================================
# 3. IMAGE ENHANCEMENT ENDPOINT
# ============================================================================

@router.post("/reels/enhance-image", response_model=EnhanceImageResponse)
@reels_router.post("/enhance-image", response_model=EnhanceImageResponse)
async def enhance_product_image_endpoint(
    request: EnhanceImageRequest,
    current_user = Depends(get_current_user)
):
    """Enhances a product photograph with commercial lighting and clarity while preserving product identity."""
    enhancer = ImageEnhancementService()
    result = await enhancer.enhance_image(
        image_url_or_path=request.image_url,
        prompt=request.prompt,
        product_name=request.product_name,
        category=request.category,
        skip_enhancement=request.skip_enhancement
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Image enhancement failed"))

    return EnhanceImageResponse(
        success=True,
        original_image_url=result["original_image_url"],
        enhanced_image_url=result["enhanced_image_url"],
        enhanced=result["enhanced"],
        provider=result.get("provider", "studio_photographic_enhancement"),
        message=result.get("message"),
        metadata=result.get("metadata")
    )


# ============================================================================
# 4. REEL GENERATION PIPELINE
# ============================================================================

@router.post("/generate-reel", response_model=ReelGenerationResponse, dependencies=[Depends(require_feature("ai_reel")), Depends(require_credits("ai_reel")), Depends(require_usage_limit("reel"))])
@reels_router.post("/generate-reel", response_model=ReelGenerationResponse, dependencies=[Depends(require_feature("ai_reel")), Depends(require_credits("ai_reel")), Depends(require_usage_limit("reel"))])
async def generate_reel(
    request: GenerateReelRequest,
    current_user = Depends(get_current_user)
):
    """Generates an AI-powered 9:16 vertical commercial marketing reel with product locking."""
    db = get_database()
    
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    if not business:
        class MockBusiness:
            id = current_user["id"]
            name = "Mock Business"
        business = MockBusiness()
        
    brand = await get_brand_kit(db, str(business.id))
    if not brand:
        brand = {}
        
    product_id = request.product_id or "general"
    product = None
    
    b_id_query = ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id)
    
    # 1. Try MongoDB ObjectId lookup in products collection
    if ObjectId.is_valid(product_id):
        doc = await db["products"].find_one({
            "_id": ObjectId(product_id),
            "business_id": b_id_query
        })
        if doc:
            product = serialize_product(doc)
            if request.category or request.product_category:
                product["category"] = request.category or request.product_category

    # 2. Check fashion_products collection if ObjectId
    if not product and ObjectId.is_valid(product_id):
        fdoc = await db["fashion_products"].find_one({"_id": ObjectId(product_id)})
        if fdoc:
            product = {
                "id": str(fdoc["_id"]),
                "name": fdoc.get("name", "Product"),
                "category": fdoc.get("category") or request.category or request.product_category or "Fashion & Apparel",
                "description": fdoc.get("description", ""),
                "price": fdoc.get("price", 0),
                "image_url": fdoc.get("image_url"),
                "images": [fdoc.get("image_url")] if fdoc.get("image_url") else []
            }

    # 3. Match by name or product_name if not found by ID
    search_name = request.product_name or (product_id if product_id not in ["general", "default", ""] else None)
    if not product and search_name and ObjectId.is_valid(str(business.id)):
        doc = await db["products"].find_one({
            "business_id": b_id_query,
            "$or": [
                {"product_id": search_name},
                {"name": {"$regex": f"^{re.escape(search_name)}$", "$options": "i"}}
            ]
        })
        if doc:
            product = serialize_product(doc)
            if request.category or request.product_category:
                product["category"] = request.category or request.product_category
        else:
            fdoc = await db["fashion_products"].find_one({
                "name": {"$regex": f"^{re.escape(search_name)}$", "$options": "i"}
            })
            if fdoc:
                product = {
                    "id": str(fdoc["_id"]),
                    "name": fdoc.get("name", search_name),
                    "category": fdoc.get("category") or request.category or request.product_category or "Fashion & Apparel",
                    "description": fdoc.get("description", ""),
                    "price": fdoc.get("price", 0),
                    "image_url": fdoc.get("image_url"),
                    "images": [fdoc.get("image_url")] if fdoc.get("image_url") else []
                }

    # 4. Check category taxonomy presets (e.g. preset_macbook, preset_sofa, etc.)
    if not product and product_id and product_id.startswith("preset_"):
        matching_presets = [p for p in get_preset_products() if p.get("id") == product_id]
        if matching_presets:
            product = dict(matching_presets[0])

    # 5. Explicit custom product supplied by user
    if not product and (request.product_name or (product_id and product_id not in ["general", "default", ""])):
        chosen_name = request.product_name or (product_id.replace("preset_", "").replace("_", " ").title())
        chosen_category = request.category or request.product_category or "Commercial Product"
        chosen_desc = request.product_description or f"High quality {chosen_name}"
        chosen_img = request.image_url or request.product_image_url
        product = {
            "id": product_id or str(ObjectId()),
            "name": chosen_name,
            "category": chosen_category,
            "description": chosen_desc,
            "price": request.price or 99.99,
            "sale_price": request.sale_price,
            "image_url": chosen_img,
            "images": [chosen_img] if chosen_img else []
        }

    # 6. Text prompt mode fallback
    if not product and request.creation_mode == "text_prompt":
        product = {
            "id": "prompt_product",
            "name": request.product_name or "Featured Product",
            "category": request.category or request.product_category or "Commercial Showcase",
            "description": request.product_description or request.additional_instructions or "High quality product showcase",
            "price": request.price or 99.99,
            "image_url": request.image_url or request.product_image_url,
            "images": [request.image_url] if request.image_url else []
        }

    # 7. Fallback if completely unspecified
    if not product:
        final_name = request.product_name or "Commercial Showcase"
        final_category = request.category or request.product_category or "General Commercial"
        final_desc = request.product_description or f"Featured Showcase of {final_name}"
        final_img = request.image_url or request.product_image_url
        product = {
            "id": product_id or "general",
            "name": final_name,
            "category": final_category,
            "description": final_desc,
            "price": 99.99,
            "image_url": final_img,
            "images": [final_img] if final_img else []
        }

    try:
        reel_service = ReelService(db)
        job_id = await reel_service.create_reel_job(
            user_id=str(current_user["id"]),
            business_id=str(business.id),
            request=request,
            product=product,
            brand=brand
        )
        
        # Deduct credits & log usage
        await CreditService.deduct_credits(db, str(current_user["id"]), "ai_reel")
        await SubscriptionService.increment_usage(db, str(current_user["id"]), "reel")
        
        return ReelGenerationResponse(
            success=True,
            job_id=job_id,
            status="queued",
            message="Reel generation started in background."
        )
    except Exception as exc:
        await CreditService.refund_credits(db, str(current_user["id"]), "ai_reel")
        raise HTTPException(status_code=500, detail=f"Failed to start reel generation: {exc}")


# ============================================================================
# 5. JOB STATUS, MANAGEMENT & RETRY
# ============================================================================

@router.get("/reel/{job_id}/status", response_model=ReelJobStatus)
@reels_router.get("/{job_id}/status", response_model=ReelJobStatus)
async def get_reel_status(
    job_id: str,
    current_user = Depends(get_current_user)
):
    """Retrieves real-time progress and artifacts of an authenticated reel generation job."""
    db = get_database()
    reel_service = ReelService(db)
    status = await reel_service.get_job_status(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Reel job not found")
        
    return status


@router.post("/reel/{job_id}/retry")
@reels_router.post("/{job_id}/retry")
async def retry_reel_endpoint(
    job_id: str,
    current_user = Depends(get_current_user)
):
    """Retries a failed reel job without re-uploading original assets or charging extra credits."""
    db = get_database()
    reel_service = ReelService(db)
    ok = await reel_service.retry_job(job_id=job_id, user_id=str(current_user["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or access denied")
    return {"success": True, "job_id": job_id, "message": "Reel job restarted successfully."}


@router.get("/reels")
@reels_router.get("")
async def get_reels(
    current_user = Depends(get_current_user)
):
    """Lists all reels generated for the authenticated user's business."""
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    if not business:
        return {"success": True, "data": []}
        
    cursor = db["reel_jobs"].find({
        "business_id": ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id)
    }).sort("created_at", -1)
    
    reels = []
    async for item in cursor:
        item["_id"] = str(item["_id"])
        if "user_id" in item and isinstance(item["user_id"], ObjectId):
            item["user_id"] = str(item["user_id"])
        if "business_id" in item and isinstance(item["business_id"], ObjectId):
            item["business_id"] = str(item["business_id"])
        reels.append(item)
        
    return {"success": True, "data": reels}


@router.get("/reel/{reel_id}")
@reels_router.get("/{reel_id}")
async def get_reel(
    reel_id: str,
    current_user = Depends(get_current_user)
):
    """Retrieves full details and generated video for a specific reel."""
    db = get_database()
    if not ObjectId.is_valid(reel_id):
        raise HTTPException(status_code=400, detail="Invalid reel ID format")
        
    item = await db["reel_jobs"].find_one({"_id": ObjectId(reel_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Reel not found")
        
    item["_id"] = str(item["_id"])
    if "user_id" in item and isinstance(item["user_id"], ObjectId):
        item["user_id"] = str(item["user_id"])
    if "business_id" in item and isinstance(item["business_id"], ObjectId):
        item["business_id"] = str(item["business_id"])
        
    return {"success": True, "data": item}


@router.delete("/reel/{reel_id}")
@reels_router.delete("/{reel_id}")
async def delete_reel(
    reel_id: str,
    current_user = Depends(get_current_user)
):
    """Deletes a generated reel and enforces ownership."""
    db = get_database()
    if not ObjectId.is_valid(reel_id):
        raise HTTPException(status_code=400, detail="Invalid reel ID format")
        
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    result = await db["reel_jobs"].delete_one({
        "_id": ObjectId(reel_id),
        "business_id": ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id)
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Reel not found")
        
    return {"success": True, "message": "Reel deleted"}
