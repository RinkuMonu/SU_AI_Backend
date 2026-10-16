from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from bson import ObjectId
import re

from app.core.security import get_current_user
from app.core.database import get_database
from app.schemas.reel import GenerateReelRequest, ReelGenerationResponse, ReelJobStatus
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products, serialize_product
from app.services.reel_service import ReelService

from app.api.dependencies import require_feature, require_credits, require_usage_limit
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService

router = APIRouter(
    prefix="/api/v1/content",
    tags=["Reels"]
)

@router.post("/generate-reel", response_model=ReelGenerationResponse, dependencies=[Depends(require_feature("ai_reel")), Depends(require_credits("ai_reel")), Depends(require_usage_limit("reel"))])
async def generate_reel(
    request: GenerateReelRequest,
    current_user = Depends(get_current_user)
):
    db = get_database()
    
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    if not business:
        class MockBusiness:
            id = current_user["id"]
            name = "Mock Business"
        business = MockBusiness()
        
    brand = await get_brand_kit(db, str(business.id))
    if not brand:
        brand = {} # Default brand kit if missing
        
    product_id = request.product_id
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
            if request.product_category:
                product["category"] = request.product_category

    # 2. Check fashion_products collection if ObjectId
    if not product and ObjectId.is_valid(product_id):
        fdoc = await db["fashion_products"].find_one({"_id": ObjectId(product_id)})
        if fdoc:
            product = {
                "id": str(fdoc["_id"]),
                "name": fdoc.get("name", "Product"),
                "category": fdoc.get("category") or request.product_category or "Fashion & Apparel",
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
            if request.product_category:
                product["category"] = request.product_category
        else:
            fdoc = await db["fashion_products"].find_one({
                "name": {"$regex": f"^{re.escape(search_name)}$", "$options": "i"}
            })
            if fdoc:
                product = {
                    "id": str(fdoc["_id"]),
                    "name": fdoc.get("name", search_name),
                    "category": fdoc.get("category") or request.product_category or "Fashion & Apparel",
                    "description": fdoc.get("description", ""),
                    "price": fdoc.get("price", 0),
                    "image_url": fdoc.get("image_url"),
                    "images": [fdoc.get("image_url")] if fdoc.get("image_url") else []
                }

    # 4. Explicit product details, custom product, or preset in request (Strictly lock to user input)
    if not product and (request.product_name or (product_id and product_id not in ["general", "default", ""])):
        chosen_name = request.product_name or (product_id.replace("preset_", "").replace("_", " ").title())
        chosen_category = request.product_category or "Commercial Product"
        chosen_desc = request.product_description or f"High quality {chosen_name}"
        chosen_img = request.product_image_url
        product = {
            "id": product_id or str(ObjectId()),
            "name": chosen_name,
            "category": chosen_category,
            "description": chosen_desc,
            "price": 99.99,
            "image_url": chosen_img,
            "images": [chosen_img] if chosen_img else []
        }

    # 5. Creative mode fallback (DO NOT substitute an arbitrary catalogue product!)
    if not product and request.generation_mode == "creative":
        product = {
            "id": "creative_general",
            "name": request.product_name or "Brand Story",
            "category": "Creative / Brand Story",
            "description": request.additional_instruction or "Creative Brand Storytelling",
            "image_url": request.product_image_url,
            "images": [request.product_image_url] if request.product_image_url else []
        }

    # 6. Fallback if completely unspecified
    if not product:
        final_name = request.product_name or "Commercial Showcase"
        final_category = request.product_category or "General Commercial"
        final_desc = request.product_description or f"Featured Showcase of {final_name}"
        final_img = request.product_image_url
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
        # Refund if queueing failed
        await CreditService.refund_credits(db, str(current_user["id"]), "ai_reel")
        raise HTTPException(status_code=500, detail=f"Failed to start reel generation: {exc}")

@router.get("/reel/{job_id}/status", response_model=ReelJobStatus)
async def get_reel_status(
    job_id: str,
    current_user = Depends(get_current_user)
):
    db = get_database()
    reel_service = ReelService(db)
    status = await reel_service.get_job_status(job_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return status

@router.get("/reels")
async def get_reels(
    current_user = Depends(get_current_user)
):
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
async def get_reel(
    reel_id: str,
    current_user = Depends(get_current_user)
):
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
async def delete_reel(
    reel_id: str,
    current_user = Depends(get_current_user)
):
    db = get_database()
    if not ObjectId.is_valid(reel_id):
        raise HTTPException(status_code=400, detail="Invalid reel ID format")
        
    business = await BusinessService.get_business_by_owner(str(current_user["id"]))
    
    result = await db["reel_jobs"].delete_one({
        "_id": ObjectId(reel_id),
        "business_id": ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id)
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Reel not found")
        
    return {"success": True, "message": "Reel deleted"}
