from fastapi import APIRouter, Depends, status, File, UploadFile, HTTPException

from app.schemas.brand import (
    BrandCreate,
    BrandUpdate,
    BrandKitSubmission,
    BrandKitStatusResponse,
    BrandKitActionResponse,
    AILogoGenerateRequest,
)

from app.services.brand_service import (
    create_brand_kit,
    get_brand_kit,
    get_brand_kit_by_owner,
    update_brand_kit,
    save_brand_kit_submission,
    get_onboarding_status,
    generate_and_save_ai_logo,
)

from app.core.security import get_current_user, require_businessman, CurrentUser
from app.core.database import get_database
from app.utils.upload import save_image, ALLOWED_EXTENSIONS, MAX_FILE_SIZE


router = APIRouter(
    tags=["Brand Kit"]
)


@router.get("/onboarding-status", response_model=BrandKitStatusResponse, operation_id="brand_get_onboarding_status")
@router.get("/status", response_model=BrandKitStatusResponse, operation_id="brand_get_status_alias")
async def get_brand_onboarding_status(
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Checks the Brand Kit onboarding status for the authenticated user.
    - If user is Businessman with incomplete/unstarted Brand Kit: returns should_show_modal=True.
    - If user is Businessman with completed Brand Kit: returns should_show_modal=False.
    - If user is Influencer: returns should_show_modal=False, brand_kit_status='not_applicable'.
    """
    return await get_onboarding_status(db, current_user)


@router.post("/draft", response_model=BrandKitActionResponse, operation_id="brand_save_draft")
async def save_draft(
    data: BrandKitSubmission,
    current_user: CurrentUser = Depends(require_businessman),
    db=Depends(get_database)
):
    """
    Saves a partial Brand Kit draft without marking it completed.
    Accepts partial inputs and persists state as 'in_progress'.
    """
    owner_id = str(current_user["id"])
    submission_dict = data.model_dump(exclude_none=True)
    brand = await save_brand_kit_submission(db, owner_id, submission_dict, is_draft=True, is_complete_action=False)
    return BrandKitActionResponse(
        success=True,
        message="Brand Kit draft saved successfully",
        brand_kit_status="in_progress",
        brand_kit_completed=False,
        completion_percentage=brand.get("completion_percentage", 0),
        completed_sections=brand.get("completed_sections", []),
        pending_sections=brand.get("pending_sections", []),
        data=brand
    )


@router.post("/submit-kit", response_model=BrandKitActionResponse, operation_id="brand_submit_kit")
@router.post("/complete", response_model=BrandKitActionResponse, operation_id="brand_complete_kit")
async def complete_brand_kit(
    data: BrandKitSubmission,
    current_user: CurrentUser = Depends(require_businessman),
    db=Depends(get_database)
):
    """
    Validates all required Brand Kit fields and marks the Brand Kit completed.
    Returns 422 with field-level errors if any required field is missing.
    """
    owner_id = str(current_user["id"])
    submission_dict = data.model_dump(exclude_none=True)
    brand = await save_brand_kit_submission(db, owner_id, submission_dict, is_draft=False, is_complete_action=True)
    return BrandKitActionResponse(
        success=True,
        message="Brand Kit completed successfully",
        brand_kit_status="completed",
        brand_kit_completed=True,
        completion_percentage=brand.get("completion_percentage", 100),
        completed_sections=brand.get("completed_sections", []),
        pending_sections=brand.get("pending_sections", []),
        data=brand
    )


@router.post("", status_code=status.HTTP_201_CREATED, operation_id="brand_create_or_save")
async def create_or_save_brand(
    data: BrandKitSubmission,
    current_user: CurrentUser = Depends(require_businessman),
    db=Depends(get_database)
):
    """
    Unified Brand Kit submission endpoint.
    Supports partial saves without blocking on optional fields.
    If all fields are completed and is_draft is False, marks as completed; otherwise saves in_progress.
    """
    owner_id = str(current_user["id"])
    submission_dict = data.model_dump(exclude_none=True)
    is_draft = getattr(data, "is_draft", False)
    brand = await save_brand_kit_submission(db, owner_id, submission_dict, is_draft=is_draft, is_complete_action=False)
    return {
        "success": True,
        "message": "Brand Kit draft saved successfully" if is_draft else "Brand Kit saved successfully",
        "brand_kit_status": brand.get("brand_kit_status"),
        "brand_kit_completed": brand.get("brand_kit_completed"),
        "completion_percentage": brand.get("completion_percentage", 0),
        "completed_sections": brand.get("completed_sections", []),
        "pending_sections": brand.get("pending_sections", []),
        "data": brand
    }


@router.get("", operation_id="brand_get_my_kit_root")
@router.get("/me", operation_id="brand_get_my_kit_me")
async def get_my_brand_kit(
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Retrieves the Brand Kit for the authenticated user.
    """
    owner_id = str(current_user["id"])
    brand = await get_brand_kit_by_owner(db, owner_id)
    return {
        "success": True,
        "message": "Brand Kit fetched successfully",
        "data": brand
    }


@router.put("", operation_id="brand_update_my_kit")
async def update_my_brand(
    data: BrandUpdate,
    current_user: CurrentUser = Depends(require_businessman),
    db=Depends(get_database)
):
    """
    Updates the existing Brand Kit for the authenticated user.
    Preserves existing saved data for omitted fields and recalculates completion.
    """
    owner_id = str(current_user["id"])
    update_dict = data.model_dump(exclude_none=True)
    brand = await save_brand_kit_submission(db, owner_id, update_dict, is_draft=False, is_complete_action=False)
    return {
        "success": True,
        "message": "Brand Kit updated successfully",
        "brand_kit_status": brand.get("brand_kit_status"),
        "brand_kit_completed": brand.get("brand_kit_completed"),
        "completion_percentage": brand.get("completion_percentage", 0),
        "completed_sections": brand.get("completed_sections", []),
        "pending_sections": brand.get("pending_sections", []),
        "data": brand
    }


@router.post("/upload-logo", operation_id="brand_upload_logo")
async def upload_brand_logo(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_businessman)
):
    """
    Uploads a business logo image file with size and extension validation.
    """
    from pathlib import Path
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format '{ext}'. Only JPG, JPEG, PNG, and WEBP are supported."
        )

    logo_url = await save_image(file, "brand")
    return {
        "success": True,
        "message": "Brand logo uploaded successfully",
        "data": {
            "logo_url": logo_url
        }
    }


@router.post("/generate-logo", operation_id="brand_generate_logo")
async def generate_ai_logo(
    request: AILogoGenerateRequest,
    current_user: CurrentUser = Depends(require_businessman),
    db=Depends(get_database)
):
    """
    Generates a professional business logo using AI, downloads and saves the asset
    directly to local storage (/uploads/brand/), and returns the verified asset reference.
    """
    owner_id = str(current_user["id"])
    result = await generate_and_save_ai_logo(db, owner_id, request)
    return {
        "success": True,
        "message": "AI Logo generated successfully",
        "data": result
    }


@router.post("/dismiss", operation_id="brand_dismiss_modal")
@router.post("/skip", operation_id="brand_skip_modal")
async def dismiss_brand_kit_modal(
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Dismisses or skips the automatic Brand Kit popup without marking it completed.
    """
    from datetime import datetime, timezone
    owner_id = str(current_user["id"])
    now = datetime.now(timezone.utc)
    
    await db["businesses"].update_one(
        {"owner_id": owner_id},
        {"$set": {"brand_kit_dismissed": True, "brand_kit_dismissed_at": now, "updated_at": now}},
        upsert=True
    )
    await db["brand_kits"].update_one(
        {"owner_id": owner_id},
        {"$set": {"brand_kit_dismissed": True, "updated_at": now}}
    )
    return {
        "success": True,
        "message": "Brand Kit modal dismissed",
        "should_show_modal": False
    }


