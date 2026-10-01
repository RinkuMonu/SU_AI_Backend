from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from bson import ObjectId

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
    
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
        
    brand = await get_brand_kit(db, str(business.id))
    if not brand:
        brand = {} # Default brand kit if missing
        
    product_id = request.product_id
    product = None
    
    # Try MongoDB ObjectId lookup first
    if ObjectId.is_valid(product_id):
        doc = await db["products"].find_one({
            "_id": ObjectId(product_id),
            "business_id": ObjectId(str(business.id))
        })
        if doc:
            product = serialize_product(doc)

    # If not found by ObjectId, try matching by name
    if not product:
        doc = await db["products"].find_one({
            "business_id": ObjectId(str(business.id)),
            "$or": [
                {"product_id": product_id},
                {"name": product_id}
            ]
        })
        if doc:
            product = serialize_product(doc)
            
    # Fallback to first product
    if not product:
        all_products = await get_products(db, str(business.id))
        if all_products:
            product = all_products[0]
            
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    # Deduct credits atomically before pushing to background
    await CreditService.deduct_credits(db, current_user.id, "reel_generation")
    
    try:
        reel_service = ReelService(db)
        job_id = await reel_service.create_reel_job(
            user_id=str(current_user.id),
            business_id=str(business.id),
            request=request,
            product=product,
            brand=brand
        )
        
        # Deduct credits & log usage
        await CreditService.deduct_credits(db, str(current_user.id), "ai_reel")
        await SubscriptionService.increment_usage(db, str(current_user.id), "reel")
        
        return ReelGenerationResponse(
            success=True,
            job_id=job_id,
            status="queued",
            message="Reel generation started in background."
        )
    except Exception as exc:
        # Refund if queueing failed
        await CreditService.refund_credits(db, str(current_user.id), "ai_reel")
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
    business = await BusinessService.get_business_by_owner(str(current_user.id))
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
        
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    
    result = await db["reel_jobs"].delete_one({
        "_id": ObjectId(reel_id),
        "business_id": ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id)
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Reel not found")
        
    return {"success": True, "message": "Reel deleted"}
