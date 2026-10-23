import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
from bson import ObjectId
from fastapi import HTTPException, status

from app.schemas.brand import (
    BrandCreate,
    BrandUpdate,
    BrandKitSubmission,
    BrandKitStatusResponse,
    AILogoGenerateRequest,
    validate_and_normalize_hex,
)
from app.ai.image.generator import ImageGenerator
from app.core.config import settings

logger = logging.getLogger(__name__)


def serialize_brand(brand: dict) -> dict:
    if not brand:
        return {}
    
    b_id = brand.get("business_id")
    if isinstance(b_id, ObjectId):
        b_id = str(b_id)
        
    _id = brand.get("_id")
    if isinstance(_id, ObjectId):
        _id = str(_id)

    return {
        "id": _id,
        "business_id": b_id,
        "owner_id": brand.get("owner_id"),
        "business_name": brand.get("business_name") or brand.get("brand_name"),
        "brand_name": brand.get("brand_name") or brand.get("business_name"),
        "business_type": brand.get("business_type"),
        "registration_number": brand.get("registration_number"),
        "business_model": brand.get("business_model"),
        "selling_model": brand.get("selling_model"),
        "business_category": brand.get("business_category"),
        "business_description": brand.get("business_description") or brand.get("brand_description"),
        "logo_url": brand.get("logo_url"),
        "logo_metadata": brand.get("logo_metadata"),
        "tagline": brand.get("tagline"),
        "primary_color": brand.get("primary_color"),
        "secondary_color": brand.get("secondary_color"),
        "accent_color": brand.get("accent_color"),
        "gradient": brand.get("gradient"),
        "font": brand.get("font") or brand.get("heading_font"),
        "heading_font": brand.get("heading_font") or brand.get("font"),
        "body_font": brand.get("body_font") or brand.get("font"),
        "brand_voice": brand.get("brand_voice") or brand.get("tone"),
        "target_audience": brand.get("target_audience"),
        "age_group": brand.get("age_group"),
        "age_groups": brand.get("age_groups") or ([brand.get("age_group")] if brand.get("age_group") else []),
        "gender": brand.get("gender"),
        "customer_type": brand.get("customer_type"),
        "location_focus": brand.get("location_focus"),
        "language": brand.get("language"),
        "generating_for": brand.get("generating_for") or [],
        "tone": brand.get("tone") or brand.get("brand_voice"),
        "brand_description": brand.get("brand_description") or brand.get("business_description"),
        "website": brand.get("website"),
        "instagram": brand.get("instagram"),
        "contact": brand.get("contact"),
        "location": brand.get("location"),
        "social_style": brand.get("social_style"),
        "brand_kit_status": brand.get("brand_kit_status", "not_started"),
        "brand_kit_completed": brand.get("brand_kit_completed", False),
        "brand_kit_completed_at": brand.get("brand_kit_completed_at"),
        "created_at": brand.get("created_at"),
        "updated_at": brand.get("updated_at"),
    }


def validate_required_brand_kit_fields(data: dict) -> dict[str, str]:
    """
    Validates required fields for Brand Kit completion according to product specs.
    Registration number is conditional and NOT mandatory for all business types.
    """
    errors: dict[str, str] = {}

    b_name = data.get("business_name") or data.get("brand_name")
    if not b_name or not str(b_name).strip():
        errors["business_name"] = "Business name is required."

    if not data.get("business_type") or not str(data["business_type"]).strip():
        errors["business_type"] = "Business type selection is required."

    if not data.get("business_model") or not str(data["business_model"]).strip():
        errors["business_model"] = "Business model selection is required."

    if not data.get("selling_model") or not str(data["selling_model"]).strip():
        errors["selling_model"] = "Selling model selection is required."

    if not data.get("business_category") or not str(data["business_category"]).strip():
        errors["business_category"] = "Business category selection is required."

    desc = data.get("business_description") or data.get("brand_description")
    if not desc or len(str(desc).strip()) < 5:
        errors["business_description"] = "Business description is required (at least 5 characters)."

    if not data.get("logo_url") or not str(data["logo_url"]).strip():
        errors["logo_url"] = "A business logo asset is required (upload an image or generate with AI)."

    if not data.get("primary_color") or not str(data["primary_color"]).strip():
        errors["primary_color"] = "Primary brand color is required."

    if not data.get("secondary_color") or not str(data["secondary_color"]).strip():
        errors["secondary_color"] = "Secondary brand color is required."

    if not data.get("accent_color") or not str(data["accent_color"]).strip():
        errors["accent_color"] = "Accent brand color is required."

    font = data.get("font") or data.get("heading_font")
    if not font or not str(font).strip():
        errors["font"] = "Brand typography font selection is required."

    age = data.get("age_group") or data.get("age_groups")
    if not age or (isinstance(age, list) and len(age) == 0):
        errors["age_group"] = "Target audience age group selection is required."

    cust = data.get("customer_type") or data.get("target_customer") or data.get("target_audience")
    if not cust or not str(cust).strip():
        errors["customer_type"] = "Customer type selection is required."

    loc = data.get("location_focus") or data.get("location")
    if not loc or (isinstance(loc, dict) and not loc.get("city") and not loc.get("state")):
        errors["location_focus"] = "Location focus is required."

    return errors


async def get_or_create_business_for_owner(db, owner_id: str, data: dict) -> dict:
    """
    Finds or provisions the business entity for the given user.
    """
    business = await db["businesses"].find_one({"owner_id": owner_id})
    now = datetime.now(timezone.utc)

    b_name = data.get("business_name") or data.get("brand_name") or "My Business"
    b_category = data.get("business_category") or "General"
    b_location = data.get("location_focus") or "India"
    if isinstance(b_location, dict):
        b_location = f"{b_location.get('city', '')}, {b_location.get('state', '')}".strip(", ") or "India"

    business_update = {
        "name": b_name,
        "category": b_category,
        "location": b_location,
        "business_type": data.get("business_type"),
        "registration_number": data.get("registration_number"),
        "business_model": data.get("business_model"),
        "selling_model": data.get("selling_model"),
        "description": data.get("business_description") or data.get("brand_description"),
        "target_customer": data.get("customer_type") or data.get("target_audience"),
        "updated_at": now,
    }
    # Clean None values from update
    business_update = {k: v for k, v in business_update.items() if v is not None}

    if not business:
        new_business = {
            "owner_id": owner_id,
            "name": b_name,
            "category": b_category,
            "location": b_location,
            "business_type": data.get("business_type"),
            "registration_number": data.get("registration_number"),
            "business_model": data.get("business_model"),
            "selling_model": data.get("selling_model"),
            "description": data.get("business_description"),
            "target_customer": data.get("customer_type"),
            "brand_kit_status": "not_started",
            "brand_kit_completed": False,
            "brand_kit_completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        res = await db["businesses"].insert_one(new_business)
        new_business["_id"] = res.inserted_id
        return new_business

    await db["businesses"].update_one(
        {"_id": business["_id"]},
        {"$set": business_update}
    )
    business.update(business_update)
    return business


async def save_brand_kit_submission(
    db,
    owner_id: str,
    submission_data: dict,
    is_draft: bool = False
) -> dict:
    """
    Saves a Brand Kit submission.
    - If is_draft=True: saves partial draft without marking completed.
    - If is_draft=False: validates all required fields, marks completed only on full validity.
    """
    now = datetime.now(timezone.utc)

    # 1. Validation check when completing
    if not is_draft:
        errors = validate_required_brand_kit_fields(submission_data)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Brand Kit validation failed: Please complete all required fields.",
                    "errors": errors,
                    "missing_fields": errors
                }
            )

    # 2. Ensure business entity exists
    business = await get_or_create_business_for_owner(db, owner_id, submission_data)
    business_id = str(business["_id"])

    # 3. Determine completion state
    if is_draft:
        brand_status = "in_progress"
        is_completed = False
        completed_at = None
    else:
        brand_status = "completed"
        is_completed = True
        completed_at = now

    # 4. Prepare brand document
    brand_dict = {k: v for k, v in submission_data.items() if v is not None and k != "is_draft"}
    brand_dict["business_id"] = ObjectId(business_id)
    brand_dict["owner_id"] = owner_id
    brand_dict["brand_kit_status"] = brand_status
    brand_dict["brand_kit_completed"] = is_completed
    brand_dict["brand_kit_completed_at"] = completed_at
    brand_dict["updated_at"] = now

    # Also sync brand_name and business_name
    if brand_dict.get("business_name") and not brand_dict.get("brand_name"):
        brand_dict["brand_name"] = brand_dict["business_name"]
    elif brand_dict.get("brand_name") and not brand_dict.get("business_name"):
        brand_dict["business_name"] = brand_dict["brand_name"]

    # 5. Upsert BrandKit document
    collection = db["brand_kits"]
    existing = await collection.find_one({
        "$or": [
            {"business_id": ObjectId(business_id)},
            {"owner_id": owner_id}
        ]
    })

    if existing:
        await collection.update_one(
            {"_id": existing["_id"]},
            {"$set": brand_dict}
        )
        updated = await collection.find_one({"_id": existing["_id"]})
    else:
        brand_dict["created_at"] = now
        res = await collection.insert_one(brand_dict)
        updated = await collection.find_one({"_id": res.inserted_id})

    # 6. Update business status in parallel
    await db["businesses"].update_one(
        {"_id": ObjectId(business_id)},
        {"$set": {
            "brand_kit_status": brand_status,
            "brand_kit_completed": is_completed,
            "brand_kit_completed_at": completed_at,
            "updated_at": now
        }}
    )

    logger.info(f"Brand kit saved for owner {owner_id} (business={business_id}, status={brand_status}, completed={is_completed})")
    return serialize_brand(updated)


async def get_brand_kit_by_owner(db, owner_id: str) -> dict | None:
    """
    Retrieves Brand Kit for the authenticated owner.
    """
    collection = db["brand_kits"]
    brand = await collection.find_one({"owner_id": owner_id})
    if not brand:
        # Check by business ownership
        business = await db["businesses"].find_one({"owner_id": owner_id})
        if business:
            brand = await collection.find_one({"business_id": business["_id"]})

    if not brand:
        return None
    return serialize_brand(brand)


async def get_onboarding_status(db, current_user) -> BrandKitStatusResponse:
    """
    Determines whether the Brand Kit Registration modal should automatically open
    for the authenticated user.
    """
    role = current_user.get("role")
    
    # 1. Influencers / Creators do NOT see the Businessman Brand Kit registration popup
    if role == "influencer":
        return BrandKitStatusResponse(
            role="influencer",
            should_show_modal=False,
            brand_kit_status="not_applicable",
            brand_kit_completed=True,
            brand_kit_completed_at=None,
            business_id=None,
            brand_kit=None
        )

    # 2. Users with no selected role
    if not role:
        return BrandKitStatusResponse(
            role=None,
            should_show_modal=False,
            brand_kit_status="role_not_selected",
            brand_kit_completed=False,
            brand_kit_completed_at=None,
            business_id=None,
            brand_kit=None
        )

    # 3. Businessman & Admin role
    owner_id = str(current_user["id"])
    business = await db["businesses"].find_one({"owner_id": owner_id})
    business_id = str(business["_id"]) if business else None

    brand = await get_brand_kit_by_owner(db, owner_id)

    # Case A: No Brand Kit at all
    if not brand:
        return BrandKitStatusResponse(
            role=role,
            should_show_modal=True,
            brand_kit_status="not_started",
            brand_kit_completed=False,
            brand_kit_completed_at=None,
            business_id=business_id,
            brand_kit=None
        )

    # Case B: Brand Kit exists
    is_completed = brand.get("brand_kit_completed", False)
    status_str = brand.get("brand_kit_status", "not_started")

    # Legacy record support: check if already fully populated prior to status flags
    if not is_completed:
        has_name = bool(brand.get("business_name") or brand.get("brand_name"))
        has_logo = bool(brand.get("logo_url"))
        has_color = bool(brand.get("primary_color"))
        if status_str == "completed" or (has_name and has_logo and has_color and status_str != "in_progress"):
            is_completed = True
            status_str = "completed"

    should_show = not is_completed

    return BrandKitStatusResponse(
        role=role,
        should_show_modal=should_show,
        brand_kit_status=status_str,
        brand_kit_completed=is_completed,
        brand_kit_completed_at=brand.get("brand_kit_completed_at"),
        business_id=business_id,
        brand_kit=brand
    )


async def generate_and_save_ai_logo(
    db,
    owner_id: str,
    req: AILogoGenerateRequest
) -> dict:
    """
    Generates a logo with AI and persists it directly into /uploads/brand/.
    Guarantees asset storage and prevents returning fake URLs on generation failures.
    """
    color_desc = ""
    if req.preferred_colors:
        color_desc = f", using colors: {', '.join(req.preferred_colors)}"

    prompt = (
        f"Minimalist modern professional brand logo for '{req.business_name}', "
        f"category: {req.business_category or 'business'}, {req.style}{color_desc}. "
        f"Clean vector graphic logo icon, centered on solid white background, 8k resolution, flat vector logo symbol"
    )

    image_gen = ImageGenerator(
        api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
        api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
    )

    try:
        gen_res = await image_gen.generate(prompt=prompt)
        temp_url = gen_res.get("image_url")
        if not temp_url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Logo generation provider failed to return an image URL."
            )

        # Download image bytes and persist to local /uploads/brand/
        filename = f"{uuid.uuid4().hex}.png"
        upload_dir = Path("uploads") / "brand"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(temp_url)
            if resp.status_code != 200 or not resp.content:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to retrieve generated logo from AI provider."
                )
            with open(file_path, "wb") as f:
                f.write(resp.content)

        local_logo_url = f"/uploads/brand/{filename}"
        return {
            "logo_url": local_logo_url,
            "prompt": prompt,
            "business_name": req.business_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Logo generation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Logo generation failed: {str(e)}"
        )


# ============================================================================
# LEGACY BACKWARD-COMPATIBLE FUNCTIONS (Preserved for existing codebase callers)
# ============================================================================

async def create_brand_kit(db, business_id: str, data: BrandCreate):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must create a business before creating a brand kit"
        )
        
    collection = db["brand_kits"]
    existing = await collection.find_one({"business_id": ObjectId(business_id)})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Brand Kit already exists for this business"
        )

    now = datetime.now(timezone.utc)
    brand_data = data.model_dump(mode="json", exclude_none=True)
    brand_data["business_id"] = ObjectId(business_id)
    brand_data["created_at"] = now
    brand_data["updated_at"] = now

    result = await collection.insert_one(brand_data)
    created = await collection.find_one({"_id": result.inserted_id})
    return serialize_brand(created)


async def get_brand_kit(db, business_id: str):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        return None

    collection = db["brand_kits"]
    brand = await collection.find_one({"business_id": ObjectId(business_id)})
    if not brand:
        return None
    return serialize_brand(brand)


async def update_brand_kit(db, business_id: str, data: BrandUpdate):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found"
        )
        
    collection = db["brand_kits"]
    update_data = data.model_dump(mode="json", exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update"
        )

    update_data["updated_at"] = datetime.now(timezone.utc)
    result = await collection.find_one_and_update(
        {"business_id": ObjectId(business_id)},
        {
            "$set": update_data,
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True,
        return_document=True
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found"
        )

    return serialize_brand(result)

