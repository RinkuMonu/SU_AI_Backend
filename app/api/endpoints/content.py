from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId

from app.core.security import get_current_user
from app.schemas.content import GeneratePostRequest
from app.ai.services.post_generation import PostGenerationService
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products, serialize_product
from app.services.content_service import ContentService
from app.core.database import get_database


router = APIRouter(
    prefix="/api/v1/content",
    tags=["Content"]
)


@router.post("/generate-post")
async def generate_post(
    request: GeneratePostRequest,
    current_user=Depends(get_current_user),
):

    db = get_database()
    from app.services.credit_service import CreditService
    
    # Check credits before generating
    await CreditService.check_credits(db, current_user.id, "post_generation")

    # ---------------------------------
    # 1. Get user's business
    # ---------------------------------

    business = await BusinessService.get_business_by_owner(str(current_user.id))

    if not business:
        print(f"DEBUG: Business not found for owner {current_user.id}. Creating default.")
        from app.schemas.business import BusinessCreate
        default_biz = BusinessCreate(
            name="My Business",
            industry="Retail",
            description="Default business created automatically.",
            target_audience="General audience",
            category="General",
            location="Online"
        )
        business = await BusinessService.create_business(str(current_user.id), default_biz)

    # ---------------------------------
    # 2. Get brand kit
    # ---------------------------------

    brand = await get_brand_kit(
        db,
        str(business.id)
    )

    # ---------------------------------
    # 3. Get products (flexible ID lookup)
    # ---------------------------------

    products_data = []
    
    # Use product_ids if provided, otherwise fallback to product_id
    target_ids = request.product_ids if request.product_ids else [request.product_id]
    
    for pid in target_ids:
        product_doc = None
        # Try MongoDB ObjectId lookup first
        if ObjectId.is_valid(pid):
            product_doc = await db["products"].find_one({
                "_id": ObjectId(pid),
                "business_id": ObjectId(str(business.id))
            })

        # If not found by ObjectId, try matching by custom product_id field or name
        if not product_doc:
            product_doc = await db["products"].find_one({
                "business_id": ObjectId(str(business.id)),
                "$or": [
                    {"product_id": pid},
                    {"name": pid}
                ]
            })

        if product_doc:
            products_data.append(serialize_product(product_doc))

    # If still no products found, use first product of the business as fallback
    if not products_data:
        all_products = await get_products(db, str(business.id))
        if all_products:
            products_data.append(all_products[0])
            
    # For backward compatibility with existing single-product references
    product = products_data[0] if products_data else {}

    # ---------------------------------
    # 4. Generate AI Post
    # ---------------------------------

    service = PostGenerationService()

    generated = await service.generate_post(
        business=business.model_dump(mode="json"),
        brand=brand,
        product=product,
        products=products_data,
        platform=request.platform,
        objective=request.objective,
        language=request.language,
        additional_instruction=request.additional_instruction,
    )

    # ---------------------------------
    # 5. Add metadata & Save to DB
    # ---------------------------------

    generated["product_id"] = request.product_id
    generated["product_ids"] = request.product_ids if request.product_ids else [request.product_id]
    generated["platform"] = request.platform
    generated["objective"] = request.objective

    # Save to database
    content_svc = ContentService(db)
    saved_doc = await content_svc.save_generated_post(
        user_id=str(current_user.id),
        business_id=str(business.id),
        payload=generated
    )

    generated["_id"] = saved_doc["_id"]

    # Deduct credits after successful generation
    await CreditService.deduct_credits(db, current_user.id, "post_generation")

    return {
        "success": True,
        "data": generated
    }
@router.put("/update")
async def save_content(
    content: dict,
    current_user=Depends(get_current_user),
):
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
        
    # Remove _id if it's a mock string
    if "_id" in content and len(str(content["_id"])) < 12:
        del content["_id"]
        
    content["business_id"] = str(business.id)
    content["user_id"] = str(current_user.id)
    
    if "_id" in content:
        # Update existing
        from bson import ObjectId
        if ObjectId.is_valid(content["_id"]):
            content_id = content.pop("_id")
            await db["contents"].update_one({"_id": ObjectId(content_id)}, {"$set": content})
            content["_id"] = content_id
    else:
        # Insert new
        result = await db["contents"].insert_one(content)
        content["_id"] = str(result.inserted_id)
        
    return {"success": True, "data": content}

@router.get("")
async def get_contents(
    current_user=Depends(get_current_user),
):
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        return {"success": True, "data": []}
        
    cursor = db["contents"].find({"business_id": str(business.id)})
    
    contents = []
    async for item in cursor:
        if "_id" in item:
            item["_id"] = str(item["_id"])
        contents.append(item)
        
    return {"success": True, "data": contents}

@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    current_user=Depends(get_current_user),
):
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
        
    from bson import ObjectId
    if not ObjectId.is_valid(content_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")
        
    result = await db["contents"].delete_one({
        "_id": ObjectId(content_id),
        "business_id": str(business.id)
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
        
    return {"success": True, "message": "Content deleted"}

