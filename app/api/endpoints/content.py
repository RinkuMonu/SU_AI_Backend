import os
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from bson import ObjectId

from app.core.security import get_current_user
from app.core.config import settings
from app.core.database import get_database
from app.schemas.content import (
    GenerateContentRequest,
    GeneratePostRequest,
    GeneratedContentResponse,
    GeneratedPost,
)
from app.ai.services.post_generation import PostGenerationService
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products, serialize_product
from datetime import datetime, timezone
from app.services.content_service import ContentService
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService
from app.services.plan_onboarding_service import QUALIFYING_PAID_PLANS


router = APIRouter(
    prefix="/api/v1/content",
    tags=["Content"]
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
MAX_IMAGE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MIN_IMAGE_SIZE_BYTES = 500  # 500 bytes


# ============================================================================
# 1. FILE UPLOADS (SINGLE & MULTIPLE PRODUCT IMAGES)
# ============================================================================

@router.post("/upload-images")
async def upload_multiple_product_images(
    files: List[UploadFile] = File(...),
    current_user=Depends(get_current_user),
):
    """Securely uploads and validates multiple authentic product images."""
    if not files:
        raise HTTPException(status_code=400, detail="No image files provided for upload.")

    dest_dir = Path("uploads") / "products"
    dest_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for file in files:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image format '{file.content_type}' for '{file.filename}'. Supported: JPEG, PNG, WebP."
            )

        content = await file.read()
        if len(content) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image '{file.filename}' exceeds maximum allowed size of 15MB."
            )

        if len(content) < MIN_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or empty image file '{file.filename}'."
            )

        ext = Path(file.filename or "image.jpg").suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"

        filename = f"prod_{uuid.uuid4().hex[:12]}{ext}"
        dest_path = dest_dir / filename

        with open(dest_path, "wb") as f:
            f.write(content)

        public_url = settings.get_public_url(f"/uploads/products/{filename}")
        uploaded.append({
            "image_id": filename,
            "image_url": public_url,
            "filename": filename,
            "original_filename": file.filename,
            "size_bytes": len(content),
            "content_type": file.content_type,
        })

    return {
        "success": True,
        "count": len(uploaded),
        "data": uploaded,
        "image_urls": [u["image_url"] for u in uploaded],
    }


@router.post("/upload-image")
async def upload_single_product_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Securely uploads and validates a single authentic product image."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image format '{file.content_type}'. Supported: JPEG, PNG, WebP."
        )

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Image size exceeds maximum limit of 15MB.")

    if len(content) < MIN_IMAGE_SIZE_BYTES:
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
        "content_type": file.content_type,
    }


# ============================================================================
# 2. PRODUCT-BASED AI CONTENT GENERATION PIPELINE
# ============================================================================

@router.post("/generate")
@router.post("/generate-post")
async def generate_post(
    request: GenerateContentRequest,
    current_user=Depends(get_current_user),
):
    """
    Unified product-based content creation endpoint.
    Supports social media posts, captions, advertisements, and reels.
    Integrates Brand Kit ON/OFF mode and validates ownership and product inputs.
    """
    db = get_database()
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])

    # ---------------------------------
    # 0. Credit Check
    # ---------------------------------
    credit_feature = "ai_reel" if request.content_type == "reel" else "post_generation"
    await CreditService.check_credits(db, user_id, credit_feature)

    # ---------------------------------
    # 1. Resolve Business
    # ---------------------------------
    business = await BusinessService.get_business_by_owner(user_id)

    if not business:
        from app.schemas.business import BusinessCreate
        default_biz = BusinessCreate(
            name="My Business",
            industry="Retail",
            description="Default business created automatically.",
            target_audience="General audience",
            category="General",
            location="Online"
        )
        business = await BusinessService.create_business(user_id, default_biz)

    # ---------------------------------
    # 2. Resolve Brand Kit (ON vs OFF)
    # ---------------------------------
    brand = None
    manual_brand = None

    if request.use_brand_kit:
        from app.services.brand_service import resolve_user_brand_config
        brand = await resolve_user_brand_config(
            db=db,
            user_id=user_id,
            business_id=str(business.id),
            require_usable=True
        )
    else:
        # User provided manual branding settings
        manual_brand = {
            "brand_name": request.brand_name,
            "brand_voice": request.brand_voice or request.tone,
            "brand_colors": request.brand_colors,
            "target_audience": request.target_audience,
            "tone": request.tone,
            "cta": request.cta,
        }

    # ---------------------------------
    # 3. Resolve Products & Ownership Validation
    # ---------------------------------
    products_data = []
    target_ids = []

    if request.product_ids:
        target_ids.extend([pid.strip() for pid in request.product_ids if pid and pid.strip()])
    elif request.product_id and request.product_id.strip():
        target_ids.append(request.product_id.strip())

    for pid in target_ids:
        product_doc = None

        if ObjectId.is_valid(pid):
            # Check products collection
            found_doc = await db["products"].find_one({"_id": ObjectId(pid)})
            if found_doc:
                # Validate ownership
                doc_biz_id = str(found_doc.get("business_id"))
                if doc_biz_id != str(business.id):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Access denied: Product '{pid}' belongs to another business."
                    )
                product_doc = found_doc
            else:
                # Check fashion_products collection
                fdoc = await db["fashion_products"].find_one({"_id": ObjectId(pid)})
                if fdoc:
                    product_doc = {
                        "_id": str(fdoc["_id"]),
                        "id": str(fdoc["_id"]),
                        "name": fdoc.get("name"),
                        "category": fdoc.get("category", "Fashion & Apparel"),
                        "description": fdoc.get("description", ""),
                        "price": fdoc.get("price", 0),
                        "image_url": fdoc.get("image_url"),
                        "images": [fdoc.get("image_url")] if fdoc.get("image_url") else []
                    }
        else:
            # Custom product_id or exact name lookup within the user's business
            product_doc = await db["products"].find_one({
                "business_id": ObjectId(str(business.id)) if ObjectId.is_valid(str(business.id)) else str(business.id),
                "$or": [
                    {"product_id": pid},
                    {"name": pid}
                ]
            })

        if product_doc:
            products_data.append(serialize_product(product_doc))
        elif not request.product_name:
            # If a specific product_id was requested but does not exist and no direct product details were given
            raise HTTPException(
                status_code=404,
                detail=f"Product '{pid}' not found."
            )

    # ---------------------------------
    # 4. Integrate Direct Product Details
    # ---------------------------------
    if request.product_name:
        direct_product = {
            "name": request.product_name,
            "description": request.product_description or "",
            "price": request.price or 0,
            "sale_price": request.sale_price,
            "category": request.category or "General",
            "features": request.features or [],
            "images": request.product_images or [],
            "image_url": request.product_images[0] if request.product_images else None,
        }
        if products_data:
            # Augment existing product with provided overrides
            products_data[0].update({k: v for k, v in direct_product.items() if v is not None and v != ""})
        else:
            products_data.append(direct_product)

    # Fallback to business catalogue only if no product or custom input was provided
    has_custom_input = bool(request.additional_instruction or request.reference_images or request.product_images)
    has_requested_products = bool(target_ids or request.product_name)

    if not products_data and not has_requested_products and not has_custom_input:
        all_products = await get_products(db, str(business.id))
        if all_products:
            products_data.append(all_products[0])

    # Primary product context (defaults to empty dict if generating general brand/business content)
    product = products_data[0] if products_data else {}

    # Validate referenced local images exist on disk
    all_image_refs = (request.product_images or []) + (request.reference_images or [])
    for img_ref in all_image_refs:
        if img_ref and "uploads/" in img_ref:
            is_external_url = (img_ref.startswith("http://") or img_ref.startswith("https://")) and not ("localhost" in img_ref or "127.0.0.1" in img_ref)
            if not is_external_url:
                rel_part = img_ref.split("uploads/")[-1].split("?")[0]
                local_path = os.path.join(os.getcwd(), "uploads", rel_part)
                if not os.path.exists(local_path):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Referenced image file '{rel_part}' does not exist on server."
                    )

    # ---------------------------------
    # 5. Handle Content Types
    # ---------------------------------
    clean_type = (request.content_type or "post").lower()

    if clean_type == "reel":
        from app.schemas.reel import GenerateReelRequest
        from app.services.reel_service import ReelService

        primary_img = (request.product_images[0] if request.product_images else product.get("image_url"))
        reel_request = GenerateReelRequest(
            product_id=request.product_id or product.get("id") or "general",
            product_name=product.get("name") or request.product_name or "Commercial Product",
            product_description=product.get("description") or request.product_description,
            category=product.get("category") or request.category,
            price=product.get("price") or request.price or 99.99,
            image_url=primary_img,
            use_brand_kit=request.use_brand_kit,
            language=request.language,
            prompt=request.additional_instruction,
        )

        reel_svc = ReelService(db)
        job_doc = await reel_svc.create_reel_job(
            user_id=user_id,
            business_id=str(business.id),
            request=reel_request,
            brand=brand,
        )
        return {
            "success": True,
            "data": job_doc
        }

    # Generate Post / Caption / Advertisement via PostGenerationService
    service = PostGenerationService()
    generated = await service.generate_post(
        business=business.model_dump(mode="json") if hasattr(business, "model_dump") else dict(business),
        brand=brand,
        product=product,
        products=products_data,
        platform=request.platform,
        objective=request.objective,
        language=request.language,
        additional_instruction=request.additional_instruction,
        reference_images=request.reference_images or [],
        product_images=request.product_images or [],
        use_brand_kit=request.use_brand_kit,
        manual_brand=manual_brand,
        content_type=clean_type,
    )

    # ---------------------------------
    # 6. Add metadata & Save to DB
    # ---------------------------------
    generated["product_id"] = request.product_id
    generated["product_ids"] = target_ids
    generated["product_details"] = product
    generated["content_type"] = clean_type
    generated["platform"] = request.platform
    generated["objective"] = request.objective
    generated["use_brand_kit"] = request.use_brand_kit
    generated["brand_kit_applied"] = bool(request.use_brand_kit and brand)

    # Save to database
    content_svc = ContentService(db)
    saved_doc = await content_svc.save_generated_post(
        user_id=user_id,
        business_id=str(business.id),
        payload=generated
    )

    generated["_id"] = str(saved_doc["_id"])
    generated["id"] = str(saved_doc["_id"])

    # Deduct credits after successful generation
    await CreditService.deduct_credits(db, user_id, credit_feature)

    return {
        "success": True,
        "data": generated
    }


@router.post("/generate-ad")
async def generate_ad_content(
    request: GenerateContentRequest,
    current_user=Depends(get_current_user),
):
    """Dedicated endpoint for product advertisement generation."""
    request.content_type = "ad"
    return await generate_post(request, current_user)


@router.post("/generate-caption")
async def generate_caption_content(
    request: GenerateContentRequest,
    current_user=Depends(get_current_user),
):
    """Dedicated endpoint for product caption generation."""
    request.content_type = "caption"
    return await generate_post(request, current_user)


# ============================================================================
# 3. CONTENT LIBRARY MANAGEMENT
# ============================================================================

@router.put("/update")
@router.put("/{content_id}")
@router.patch("/{content_id}")
async def save_content(
    content: dict,
    content_id: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """
    Saves edits against the correct post in place without creating unintentional duplicates.
    Enforces user ownership and plan entitlements on locked posts.
    """
    db = get_database()
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    business = await BusinessService.get_business_by_owner(user_id)
    business_id = str(business.id) if business else None

    now = datetime.now(timezone.utc)
    if content_id and content_id.strip() == "update":
        content_id = None

    target_id = (
        content_id or
        content.get("_id") or
        content.get("id") or
        content.get("content_id") or
        content.get("post_id")
    )

    if target_id and str(target_id).strip():
        target_str = str(target_id).strip()
        if not ObjectId.is_valid(target_str):
            raise HTTPException(status_code=400, detail="Invalid post ID format")

        obj_id = ObjectId(target_str)
        existing = await db["contents"].find_one({"_id": obj_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Post not found")

        # Strict ownership authorization: ensure user owns this post
        doc_user_id = str(existing.get("user_id", ""))
        doc_business_id = str(existing.get("business_id", ""))
        is_owner = (doc_user_id == user_id) or (business_id and doc_business_id == business_id)
        if not is_owner:
            raise HTTPException(status_code=403, detail="You do not have permission to modify this post.")

        # Entitlement check: if post is locked, user must have an active paid plan
        if existing.get("is_locked", False):
            sub = await SubscriptionService.get_or_create_subscription(db, user_id)
            plan_id = str(sub.get("plan_id", "FREE")).upper()
            sub_status = sub.get("status", "active")
            is_paid = (plan_id in QUALIFYING_PAID_PLANS) and (sub_status == "active")
            if not is_paid:
                raise HTTPException(
                    status_code=403,
                    detail="This post is locked and requires an active Starter or Pro subscription plan to edit."
                )

        # Update post in place without creating duplicates
        update_fields = dict(content)
        for k in ["_id", "id", "content_id", "post_id"]:
            update_fields.pop(k, None)

        update_fields["updated_at"] = now
        # Keep media_url and image_url in sync
        if update_fields.get("image_url") and not update_fields.get("media_url"):
            update_fields["media_url"] = update_fields["image_url"]
        elif update_fields.get("media_url") and not update_fields.get("image_url"):
            update_fields["image_url"] = update_fields["media_url"]

        await db["contents"].update_one(
            {"_id": obj_id},
            {"$set": update_fields}
        )

        existing.update(update_fields)
        existing["_id"] = str(obj_id)
        existing["id"] = str(obj_id)
        return {"success": True, "data": existing, "message": "Post updated successfully"}

    else:
        # Create new content item
        clean_doc = dict(content)
        for k in ["_id", "id", "content_id", "post_id"]:
            clean_doc.pop(k, None)

        clean_doc["user_id"] = user_id
        clean_doc["business_id"] = business_id or ""
        clean_doc["created_at"] = now
        clean_doc["updated_at"] = now
        if clean_doc.get("image_url") and not clean_doc.get("media_url"):
            clean_doc["media_url"] = clean_doc["image_url"]
        elif clean_doc.get("media_url") and not clean_doc.get("image_url"):
            clean_doc["image_url"] = clean_doc["media_url"]

        res = await db["contents"].insert_one(clean_doc)
        clean_doc["_id"] = str(res.inserted_id)
        clean_doc["id"] = str(res.inserted_id)
        return {"success": True, "data": clean_doc, "message": "Post created successfully"}


@router.get("")
async def get_contents(
    current_user=Depends(get_current_user),
):
    db = get_database()
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    business = await BusinessService.get_business_by_owner(user_id)
    business_id = str(business.id) if business else None

    query = {"$or": [{"user_id": user_id}]}
    if business_id:
        query["$or"].append({"business_id": business_id})

    cursor = db["contents"].find(query).sort("created_at", -1)

    contents = []
    async for item in cursor:
        if "_id" in item:
            item["_id"] = str(item["_id"])
            item["id"] = str(item["_id"])
        contents.append(item)

    return {"success": True, "data": contents}


@router.get("/{content_id}")
async def get_single_content(
    content_id: str,
    current_user=Depends(get_current_user),
):
    """
    Retrieves a single generated post asset by ID with strict ownership authorization
    and plan entitlement checks. Returns all fields needed to prepopulate the editor.
    """
    db = get_database()
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    business = await BusinessService.get_business_by_owner(user_id)
    business_id = str(business.id) if business else None

    content_svc = ContentService(db)
    doc = await content_svc.get_content_by_id(content_id, business_id=business_id, user_id=user_id)
    if not doc:
        # Check if the document exists under another user to return 403 Forbidden
        if ObjectId.is_valid(content_id):
            other_doc = await db["contents"].find_one({"_id": ObjectId(content_id)})
            if other_doc:
                raise HTTPException(status_code=403, detail="You do not have permission to access this post.")
        raise HTTPException(status_code=404, detail="Post not found")

    # Enforce plan entitlement on locked posts
    if doc.get("is_locked", False):
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        plan_id = str(sub.get("plan_id", "FREE")).upper()
        sub_status = sub.get("status", "active")
        is_paid = (plan_id in QUALIFYING_PAID_PLANS) and (sub_status == "active")
        if not is_paid:
            raise HTTPException(
                status_code=403,
                detail="This post is locked and requires an active Starter or Pro subscription plan."
            )

    # Ensure all prepopulation fields are present and synced
    doc["_id"] = str(doc["_id"])
    doc["id"] = str(doc["_id"])
    if not doc.get("image_url") and doc.get("media_url"):
        doc["image_url"] = doc["media_url"]
    elif not doc.get("media_url") and doc.get("image_url"):
        doc["media_url"] = doc["image_url"]
    if not doc.get("caption") and doc.get("primary_text"):
        doc["caption"] = doc["primary_text"]

    return {"success": True, "data": doc}


@router.delete("/{content_id}")
async def delete_content(
    content_id: str,
    current_user=Depends(get_current_user),
):
    db = get_database()
    user_id = str(current_user.id if hasattr(current_user, "id") else current_user["id"])
    business = await BusinessService.get_business_by_owner(user_id)
    business_id = str(business.id) if business else None

    if not ObjectId.is_valid(content_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")

    obj_id = ObjectId(content_id)
    existing = await db["contents"].find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Post not found")

    doc_user_id = str(existing.get("user_id", ""))
    doc_business_id = str(existing.get("business_id", ""))
    is_owner = (doc_user_id == user_id) or (business_id and doc_business_id == business_id)
    if not is_owner:
        raise HTTPException(status_code=403, detail="You do not have permission to delete this post.")

    await db["contents"].delete_one({"_id": obj_id})
    return {"success": True, "message": "Content deleted"}

