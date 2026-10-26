import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
from PIL import Image
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


BRAND_KIT_SECTIONS = {
    "business_identity": {
        "label": "Business Identity",
        "fields": ["business_name", "business_type", "business_category", "business_description"],
    },
    "business_model": {
        "label": "Business Model",
        "fields": ["business_model", "selling_model"],
    },
    "visual_identity": {
        "label": "Visual Identity",
        "fields": ["logo_url", "primary_color", "secondary_color"],
    },
    "typography_voice": {
        "label": "Typography & Voice",
        "fields": ["font", "brand_voice"],
    },
    "target_market": {
        "label": "Target Market",
        "fields": ["age_group", "customer_type", "location_focus"],
    }
}


def is_field_meaningful(field_name: str, brand_data: dict) -> bool:
    if not brand_data or not isinstance(brand_data, dict):
        return False
    val = brand_data.get(field_name)

    if field_name in ["business_name", "brand_name"]:
        name = brand_data.get("business_name") or brand_data.get("brand_name")
        return bool(name and str(name).strip())

    if field_name in ["business_description", "brand_description"]:
        desc = brand_data.get("business_description") or brand_data.get("brand_description")
        return bool(desc and len(str(desc).strip()) >= 5)

    if field_name in ["font", "heading_font"]:
        f = brand_data.get("font") or brand_data.get("heading_font")
        return bool(f and str(f).strip())

    if field_name in ["brand_voice", "tone"]:
        v = brand_data.get("brand_voice") or brand_data.get("tone")
        return bool(v and str(v).strip())

    if field_name in ["age_group", "age_groups"]:
        ag = brand_data.get("age_group")
        ags = brand_data.get("age_groups")
        return bool((ag and str(ag).strip()) or (isinstance(ags, list) and len(ags) > 0))

    if field_name in ["customer_type", "target_audience"]:
        cust = brand_data.get("customer_type") or brand_data.get("target_customer") or brand_data.get("target_audience")
        return bool(cust and str(cust).strip())

    if field_name in ["location_focus", "location"]:
        loc = brand_data.get("location_focus") or brand_data.get("location")
        if isinstance(loc, dict):
            return bool(loc.get("city") or loc.get("state"))
        return bool(loc and str(loc).strip())

    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return True


def calculate_brand_kit_completion(brand_data: dict) -> dict:
    """
    Calculates completion percentage, completed sections, and pending sections
    from meaningful saved fields across the 5 canonical Brand Kit onboarding sections.
    """
    if not brand_data or not isinstance(brand_data, dict):
        return {
            "completion_percentage": 0,
            "completed_sections": [],
            "pending_sections": list(BRAND_KIT_SECTIONS.keys()),
            "missing_fields": [],
            "completed_fields": []
        }

    completed_sections = []
    pending_sections = []
    completed_fields = []
    missing_fields = []

    total_core_fields = 0

    for section_key, section_info in BRAND_KIT_SECTIONS.items():
        section_fields = section_info["fields"]
        total_core_fields += len(section_fields)
        section_all_complete = True

        for f in section_fields:
            if is_field_meaningful(f, brand_data):
                completed_fields.append(f)
            else:
                section_all_complete = False
                missing_fields.append(f)

        if section_all_complete:
            completed_sections.append(section_key)
        else:
            pending_sections.append(section_key)

    if len(completed_sections) == len(BRAND_KIT_SECTIONS):
        pct = 100
    else:
        pct = int(round((len(completed_fields) / float(total_core_fields)) * 100))
        pct = max(0, min(99, pct))

    return {
        "completion_percentage": pct,
        "completed_sections": completed_sections,
        "pending_sections": pending_sections,
        "missing_fields": missing_fields,
        "completed_fields": completed_fields
    }


def serialize_brand(brand: dict) -> dict:
    if not brand:
        return {}
    
    b_id = brand.get("business_id")
    if isinstance(b_id, ObjectId):
        b_id = str(b_id)
        
    _id = brand.get("_id")
    if isinstance(_id, ObjectId):
        _id = str(_id)

    comp_pct = brand.get("completion_percentage")
    comp_sec = brand.get("completed_sections")
    pend_sec = brand.get("pending_sections")

    if comp_pct is None or comp_sec is None or pend_sec is None:
        calc = calculate_brand_kit_completion(brand)
        comp_pct = calc["completion_percentage"]
        comp_sec = calc["completed_sections"]
        pend_sec = calc["pending_sections"]

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
        "completion_percentage": comp_pct,
        "completed_sections": comp_sec,
        "pending_sections": pend_sec,
        "partial_saved": bool(brand.get("partial_saved", False)),
        "brand_kit_dismissed": bool(brand.get("brand_kit_dismissed", False)),
        "is_draft": bool(brand.get("is_draft", False)),
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
            "description": data.get("business_description") or data.get("brand_description"),
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
    is_draft: bool = False,
    is_complete_action: bool = False
) -> dict:
    """
    Saves a Brand Kit submission with partial save support and data preservation.
    - If is_complete_action=True: validates all required fields, marks completed on full validity.
    - If is_complete_action=False: saves partial Brand Kit (draft or update), preserves omitted/existing data,
      calculates completion percentage, and marks completed only if completion percentage reaches 100%.
    """
    now = datetime.now(timezone.utc)
    collection = db["brand_kits"]

    # 1. Fetch existing Brand Kit
    existing = await collection.find_one({"owner_id": owner_id})
    if not existing:
        biz = await db["businesses"].find_one({"owner_id": owner_id})
        if biz:
            existing = await collection.find_one({"business_id": biz["_id"]})

    # 2. Merge submission_data over existing data
    # Preserve existing saved values when optional fields are omitted or sent as empty
    merged = dict(existing) if existing else {}
    for k, v in submission_data.items():
        if k in ["is_draft", "_id"]:
            continue
        # Skip null or empty string overwriting existing non-empty values
        if v is None:
            continue
        if isinstance(v, str) and not v.strip() and existing and existing.get(k):
            continue
        merged[k] = v

    # Sync name and description aliases
    if merged.get("business_name") and not merged.get("brand_name"):
        merged["brand_name"] = merged["business_name"]
    elif merged.get("brand_name") and not merged.get("business_name"):
        merged["business_name"] = merged["brand_name"]

    if merged.get("business_description") and not merged.get("brand_description"):
        merged["brand_description"] = merged["business_description"]
    elif merged.get("brand_description") and not merged.get("business_description"):
        merged["business_description"] = merged["brand_description"]

    # 3. Essential validation: Business name must be present (from payload or existing record)
    b_name = merged.get("business_name") or merged.get("brand_name")
    if not b_name or not str(b_name).strip():
        biz = await db["businesses"].find_one({"owner_id": owner_id})
        if biz and biz.get("name") and biz.get("name") != "My Business":
            merged["business_name"] = str(biz["name"]).strip()
            merged["brand_name"] = str(biz["name"]).strip()
        elif is_draft:
            merged["business_name"] = "Draft Business"
            merged["brand_name"] = "Draft Business"
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Business name is required to save Brand Kit.",
                    "errors": {"business_name": "Business name is required."},
                    "missing_fields": {"business_name": "Business name is required."}
                }
            )

    # 4. Calculate Brand Kit completion from meaningful saved fields
    comp_info = calculate_brand_kit_completion(merged)
    completion_percentage = comp_info["completion_percentage"]
    completed_sections = comp_info["completed_sections"]
    pending_sections = comp_info["pending_sections"]

    # 5. Full completion validation if calling explicit completion action (/complete or /submit-kit)
    if is_complete_action:
        errors = validate_required_brand_kit_fields(merged)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Brand Kit validation failed: Please complete all required fields.",
                    "errors": errors,
                    "missing_fields": errors
                }
            )

    # 6. Determine completion state
    if is_draft:
        brand_status = "in_progress"
        is_completed = False
        completed_at = None
    elif is_complete_action or completion_percentage == 100:
        brand_status = "completed"
        is_completed = True
        completed_at = existing.get("brand_kit_completed_at") if (existing and existing.get("brand_kit_completed_at")) else now
    else:
        # Partial save on create/update endpoints
        brand_status = "in_progress"
        is_completed = False
        completed_at = None

    # 7. Ensure business entity exists and syncs
    business = await get_or_create_business_for_owner(db, owner_id, merged)
    business_id = str(business["_id"])

    # 8. Prepare final brand document
    brand_dict = {k: v for k, v in merged.items() if k not in ["_id", "is_draft"]}
    brand_dict["business_id"] = ObjectId(business_id)
    brand_dict["owner_id"] = owner_id
    brand_dict["brand_kit_status"] = brand_status
    brand_dict["brand_kit_completed"] = is_completed
    brand_dict["brand_kit_completed_at"] = completed_at
    brand_dict["completion_percentage"] = completion_percentage
    brand_dict["completed_sections"] = completed_sections
    brand_dict["pending_sections"] = pending_sections
    brand_dict["updated_at"] = now
    brand_dict["is_draft"] = is_draft
    if not is_draft:
        brand_dict["partial_saved"] = True

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

    # 9. Update business status in parallel
    await db["businesses"].update_one(
        {"_id": ObjectId(business_id)},
        {"$set": {
            "brand_kit_status": brand_status,
            "brand_kit_completed": is_completed,
            "brand_kit_completed_at": completed_at,
            "updated_at": now
        }}
    )

    logger.info(f"Brand kit saved for owner {owner_id} (business={business_id}, status={brand_status}, completed={is_completed}, completion={completion_percentage}%)")
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


def verify_logo_asset(logo_url: Optional[str]) -> Optional[str]:
    """
    Verifies that a logo asset exists and is accessible.
    Supports both local uploads (/uploads/...) and remote HTTP URLs.
    Returns normalized accessible logo URL or None if unavailable.
    """
    if not logo_url or not isinstance(logo_url, str):
        return None
    clean = logo_url.strip()
    if not clean:
        return None

    # Check local uploads
    if "uploads/" in clean:
        rel_path = clean.split("uploads/")[-1].split("?")[0]
        local_path = os.path.join(os.getcwd(), "uploads", rel_path)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 100:
            return settings.get_public_url(f"/uploads/{rel_path.replace(os.sep, '/')}")
        logger.warning(f"Brand logo file not found on local disk: {local_path}")
        return None

    # Check remote HTTP(S) URL
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean

    return None


async def resolve_user_brand_config(
    db,
    user_id: str,
    business_id: Optional[str] = None,
    require_usable: bool = True
) -> dict:
    """
    Securely resolves the authenticated user's saved Brand Kit.
    Validates usability, normalizes fields, verifies logo accessibility,
    and returns a structured brand configuration.
    Raises structured HTTPException 400 if Brand Kit is missing or incomplete.
    """
    brand = None
    if user_id:
        brand = await get_brand_kit_by_owner(db, str(user_id))

    if not brand and business_id and ObjectId.is_valid(str(business_id)):
        brand = await get_brand_kit(db, str(business_id))

    if not brand:
        if require_usable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Brand Kit is not configured. Please complete your Brand Kit or disable Brand Kit mode.",
                    "code": "BRAND_KIT_MISSING",
                    "missing_fields": ["business_name", "primary_color", "brand_voice"]
                }
            )
        return None

    # Usability validation: check critical branding fields
    missing_fields = []
    b_name = brand.get("business_name") or brand.get("brand_name")
    if not b_name or not str(b_name).strip():
        missing_fields.append("business_name")

    primary_color = brand.get("primary_color")
    if not primary_color or not str(primary_color).strip():
        missing_fields.append("primary_color")

    # If Brand Kit was explicitly marked as not started and has no details
    if brand.get("brand_kit_status") == "not_started" and not primary_color and not b_name:
        missing_fields.extend(["business_name", "primary_color"])

    if missing_fields and require_usable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"Brand Kit is incomplete ({', '.join(set(missing_fields))} missing). Please complete your Brand Kit or disable Brand Kit mode.",
                "code": "BRAND_KIT_INCOMPLETE",
                "missing_fields": list(set(missing_fields))
            }
        )

    # Asset verification: ensure logo is valid and accessible
    raw_logo = brand.get("logo_url")
    verified_logo = verify_logo_asset(raw_logo)

    # Normalize into consistent internal brand configuration
    normalized = {
        "id": brand.get("id"),
        "business_id": brand.get("business_id") or (str(business_id) if business_id else None),
        "owner_id": str(user_id),
        "business_name": b_name or "Our Brand",
        "brand_name": b_name or "Our Brand",
        "business_category": brand.get("business_category") or "General",
        "business_description": brand.get("business_description") or brand.get("brand_description") or "",
        "tagline": brand.get("tagline") or "",
        "primary_color": primary_color or "#7928CA",
        "secondary_color": brand.get("secondary_color"),
        "accent_color": brand.get("accent_color"),
        "font": brand.get("font") or brand.get("heading_font") or "Montserrat",
        "heading_font": brand.get("heading_font") or brand.get("font") or "Montserrat",
        "body_font": brand.get("body_font") or brand.get("font") or "Inter",
        "brand_voice": brand.get("brand_voice") or brand.get("tone") or "Inspiring, authentic, premium",
        "tone": brand.get("tone") or brand.get("brand_voice") or "energetic",
        "visual_style": brand.get("social_style") or "commercial high quality",
        "social_style": brand.get("social_style"),
        "target_audience": brand.get("target_audience") or brand.get("customer_type") or "",
        "customer_type": brand.get("customer_type") or "",
        "logo_url": verified_logo,
        "logo_metadata": brand.get("logo_metadata"),
        "logo_available": verified_logo is not None,
        "brand_kit_status": brand.get("brand_kit_status", "completed"),
        "brand_kit_completed": brand.get("brand_kit_completed", True),
    }

    return normalized


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
            completion_percentage=100,
            completed_sections=list(BRAND_KIT_SECTIONS.keys()),
            pending_sections=[],
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
            completion_percentage=0,
            completed_sections=[],
            pending_sections=list(BRAND_KIT_SECTIONS.keys()),
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
            completion_percentage=0,
            completed_sections=[],
            pending_sections=list(BRAND_KIT_SECTIONS.keys()),
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

    # Stop forcing popup to reopen if user has already saved a partial profile or dismissed
    is_dismissed = bool(
        brand.get("brand_kit_dismissed", False) or
        (business and business.get("brand_kit_dismissed", False))
    )
    is_partial_saved = bool(brand.get("partial_saved", False))
    should_show = (not is_completed) and (not is_dismissed) and (not is_partial_saved)

    return BrandKitStatusResponse(
        role=role,
        should_show_modal=should_show,
        brand_kit_status=status_str,
        brand_kit_completed=is_completed,
        brand_kit_completed_at=brand.get("brand_kit_completed_at"),
        business_id=business_id,
        completion_percentage=brand.get("completion_percentage", 0),
        completed_sections=brand.get("completed_sections", []),
        pending_sections=brand.get("pending_sections", []),
        brand_kit=brand
    )


LOGO_STYLE_MAP = {
    "minimalist_modern": "minimalist modern vector logo symbol, clean geometric lines, iconic silhouette, flat 2D graphic design, solid white background, high contrast, professional corporate branding",
    "luxury_premium": "ultra-luxurious premium brand emblem, elegant refined gold and platinum accents, high-end boutique aesthetic, exquisite symmetry, prestigious royal heraldic motif, clean solid studio background, master craftsmanship",
    "geometric_abstract": "abstract geometric logo mark, mathematical precision, golden ratio composition, modern isometric vector symbol, sharp architectural lines, centered, clean solid background, timeless minimalist tech branding",
    "3d_dimensional": "premium 3D dimensional brand logo icon, smooth ceramic, glass and metallic textures, subtle soft ambient occlusion shadow, centered isometric perspective, modern app icon aesthetic, clean solid studio background, 8k render",
    "tech_futuristic": "futuristic technology cybernetic logo mark, sleek neon gradients, circuit and neural nodes, cutting-edge AI software branding, centered vector emblem, clean dark solid background, silicon valley startup aesthetic",
    "elegant_monogram": "sophisticated luxury monogram emblem featuring stylized initials, timeless haute-couture typography, interlocking ligatures, classic luxury fashion house crest, centered, clean solid background",
    "mascot_illustrated": "modern friendly brand character mascot logo, distinctive vector illustration, bold outlines, expressive personality, esports and modern lifestyle brand aesthetic, centered emblem, clean solid background",
    "organic_natural": "organic botanical eco-friendly logo symbol, elegant leaf and sprout motifs, flowing natural curves, sustainable green lifestyle brand aesthetic, harmonious earth tones, clean vector graphic, solid clean background",
    "bold_playful": "bold vibrant playful brand logo mark, dynamic pop-art geometry, energetic friendly curves, creative agency aesthetic, high contrast colorful shapes, centered, clean solid background",
    "emblem_badge": "vintage modern heritage seal badge emblem, circular crest with delicate engraving details, artisanal craft insignia, authentic stamp logo, centered, clean solid background",
}


async def generate_and_save_ai_logo(
    db,
    owner_id: str,
    req: AILogoGenerateRequest
) -> dict:
    """
    Generates a professional business logo using AI, verifies the image asset,
    persists it directly to /uploads/brand/, and returns fully qualified asset URLs and variations.
    Guarantees asset storage and prevents returning fake URLs on generation failures.
    """
    import random
    import shutil

    # 1. Resolve business name gracefully (from payload, business entity, or brand kit)
    b_name = (req.business_name or req.brand_name or "").strip()
    if not b_name:
        biz = await db["businesses"].find_one({"owner_id": owner_id})
        if biz and biz.get("name"):
            b_name = str(biz["name"]).strip()
        else:
            brand_doc = await db["brand_kits"].find_one({"owner_id": owner_id})
            if brand_doc and (brand_doc.get("business_name") or brand_doc.get("brand_name")):
                b_name = str(brand_doc.get("business_name") or brand_doc.get("brand_name")).strip()

    if not b_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a business name to generate your brand logo."
        )

    # 2. Build detailed, style-specific logo prompt
    style_key = req.style or "minimalist_modern"
    style_desc = LOGO_STYLE_MAP.get(style_key, style_key)

    color_desc = ""
    if req.preferred_colors and len(req.preferred_colors) > 0:
        color_desc = f", incorporating brand colors ({', '.join(req.preferred_colors)})"

    guidance_desc = ""
    if req.prompt and req.prompt.strip():
        guidance_desc = f", visual theme: {req.prompt.strip()}"

    tagline_desc = ""
    if req.tagline and req.tagline.strip():
        tagline_desc = f", reflecting brand essence '{req.tagline.strip()}'"

    voice_desc = ""
    if req.brand_voice or req.personality:
        voice_desc = f", brand tone: {req.brand_voice or req.personality}"

    if req.transparent_background:
        bg_clause = "isolated vector asset, pure solid flat white background, easy to extract with transparent backdrop, no scene clutter"
    else:
        bg_clause = "isolated vector symbol, centered on clean solid background, uncluttered studio backdrop"

    prompt = (
        f"Professional brand logo for '{b_name}', category: {req.business_category or 'business'}, {style_desc}{color_desc}{guidance_desc}{tagline_desc}{voice_desc}. "
        f"{bg_clause}, 8k resolution, flat vector logo symbol, sharp crisp lines, master designer emblem, "
        f"strictly no human photo, no face, no skin pores, no t-shirt mockup, no 3D wall mockup, no blurry elements, no watermark"
    )

    primary_seed = req.variation_seed if req.variation_seed is not None else random.randint(10000, 999999)

    image_gen = ImageGenerator(
        api_url=getattr(settings, "IMAGE_API_URL", None),
        api_key=getattr(settings, "IMAGE_API_KEY", None) or getattr(settings, "GEMINI_API_KEY", None)
    )

    upload_dir = Path("uploads") / "brand"
    upload_dir.mkdir(parents=True, exist_ok=True)
    primary_filename = f"{uuid.uuid4().hex}.png"
    primary_file_path = upload_dir / primary_filename

    try:
        gen_res = await image_gen.generate(prompt=prompt, seed=primary_seed)
        temp_url = gen_res.get("image_url") if isinstance(gen_res, dict) else None
        gen_local_path = gen_res.get("local_path") if isinstance(gen_res, dict) else None

        # Case A: Generated image already saved locally by generator
        if gen_local_path and os.path.exists(gen_local_path):
            shutil.copy2(gen_local_path, primary_file_path)
        # Case B: Local candidate in uploads
        elif temp_url and "/uploads/" in str(temp_url):
            rel_temp = str(temp_url).split("/uploads/")[-1]
            candidate_p = Path("uploads") / rel_temp
            if candidate_p.exists():
                shutil.copy2(candidate_p, primary_file_path)
            elif temp_url.startswith("http"):
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(temp_url)
                    if resp.status_code == 200 and resp.content:
                        with open(primary_file_path, "wb") as f:
                            f.write(resp.content)
        # Case C: Generator returned remote URL
        elif temp_url and temp_url.startswith("http"):
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(temp_url)
                if resp.status_code != 200 or not resp.content:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Failed to retrieve generated logo from AI provider."
                    )
                with open(primary_file_path, "wb") as f:
                    f.write(resp.content)
        # Case D: Generator returned relative path
        elif temp_url and os.path.exists(temp_url.lstrip("/")):
            shutil.copy2(temp_url.lstrip("/"), primary_file_path)
        else:
            # Fallback to local artistic designer
            try:
                from app.ai.image.logo_designer import generate_artistic_brand_logo
                generate_artistic_brand_logo(
                    business_name=b_name,
                    target_path=str(primary_file_path),
                    seed=primary_seed
                )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Logo generation provider failed to produce a valid image asset."
                )

        if not os.path.exists(primary_file_path) or os.path.getsize(primary_file_path) == 0:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Logo generation provider failed to produce a valid image asset."
            )

        # Verify image format and integrity using PIL
        try:
            with Image.open(primary_file_path) as verified_img:
                verified_img.verify()
        except Exception as img_err:
            logger.warning(f"Generated logo image format check warning: {img_err}")

        local_logo_url = f"/uploads/brand/{primary_filename}"
        public_logo_url = settings.get_public_url(local_logo_url)

        # Build variations list with fully qualified URLs
        variations = [
            {
                "logo_url": public_logo_url,
                "seed": primary_seed,
                "style": style_key
            }
        ]

        # Generate additional variations if requested
        requested_variations = req.num_variations or 1
        if requested_variations > 1:
            for v_idx in range(1, requested_variations):
                v_seed = primary_seed + (v_idx * 7919)
                v_filename = f"{uuid.uuid4().hex}.png"
                v_file_path = upload_dir / v_filename
                try:
                    v_res = await image_gen.generate(prompt=prompt, seed=v_seed)
                    v_url = v_res.get("image_url") if isinstance(v_res, dict) else None
                    v_local = v_res.get("local_path") if isinstance(v_res, dict) else None
                    if v_local and os.path.exists(v_local):
                        shutil.copy2(v_local, v_file_path)
                        variations.append({
                            "logo_url": settings.get_public_url(f"/uploads/brand/{v_filename}"),
                            "seed": v_seed,
                            "style": style_key
                        })
                    elif v_url and "/uploads/" in str(v_url):
                        rel_v = str(v_url).split("/uploads/")[-1]
                        candidate_v = Path("uploads") / rel_v
                        if candidate_v.exists():
                            shutil.copy2(candidate_v, v_file_path)
                            variations.append({
                                "logo_url": settings.get_public_url(f"/uploads/brand/{v_filename}"),
                                "seed": v_seed,
                                "style": style_key
                            })
                    elif v_url and v_url.startswith("http"):
                        async with httpx.AsyncClient(timeout=25.0) as client:
                            v_resp = await client.get(v_url)
                            if v_resp.status_code == 200 and len(v_resp.content) > 0:
                                with open(v_file_path, "wb") as f_v:
                                    f_v.write(v_resp.content)
                                variations.append({
                                    "logo_url": settings.get_public_url(f"/uploads/brand/{v_filename}"),
                                    "seed": v_seed,
                                    "style": style_key
                                })
                except Exception as v_err:
                    logger.warning(f"Variation {v_idx} generation failed non-fatally: {v_err}")

        # Optional auto-save to brand kit if requested
        if req.save_to_brand_kit:
            now = datetime.now(timezone.utc)
            existing_brand = await db["brand_kits"].find_one({"owner_id": owner_id})
            logo_meta = {
                "prompt": prompt,
                "style": style_key,
                "seed": primary_seed,
                "generated_at": now.isoformat()
            }
            if existing_brand:
                merged_brand = {**existing_brand, "logo_url": public_logo_url, "logo_metadata": logo_meta}
                comp_info = calculate_brand_kit_completion(merged_brand)
                update_set = {
                    "logo_url": public_logo_url,
                    "logo_metadata": logo_meta,
                    "completion_percentage": comp_info["completion_percentage"],
                    "completed_sections": comp_info["completed_sections"],
                    "pending_sections": comp_info["pending_sections"],
                    "updated_at": now
                }
                if comp_info["completion_percentage"] == 100:
                    update_set["brand_kit_status"] = "completed"
                    update_set["brand_kit_completed"] = True
                    if not existing_brand.get("brand_kit_completed_at"):
                        update_set["brand_kit_completed_at"] = now
                await db["brand_kits"].update_one(
                    {"owner_id": owner_id},
                    {"$set": update_set}
                )
            else:
                await save_brand_kit_submission(
                    db=db,
                    owner_id=owner_id,
                    submission_data={
                        "business_name": b_name,
                        "logo_url": public_logo_url,
                        "logo_metadata": logo_meta
                    },
                    is_draft=True
                )

        return {
            "logo_url": public_logo_url,
            "prompt": prompt,
            "business_name": b_name,
            "style": style_key,
            "seed": primary_seed,
            "variations": variations
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


class BrandService:
    get_onboarding_status = staticmethod(get_onboarding_status)
    save_brand_kit_submission = staticmethod(save_brand_kit_submission)
    get_brand_kit_by_owner = staticmethod(get_brand_kit_by_owner)
    get_brand_kit = staticmethod(get_brand_kit)
    create_brand_kit = staticmethod(create_brand_kit)
    update_brand_kit = staticmethod(update_brand_kit)
    generate_and_save_ai_logo = staticmethod(generate_and_save_ai_logo)

