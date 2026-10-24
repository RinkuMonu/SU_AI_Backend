import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status
)

from app.core.security import get_current_user, CurrentUser
from app.schemas.onboarding_v2 import (
    OnlinePresenceRequest,
    OnlinePresenceResponse,
    BusinessLinkCreate,
    BusinessLinkUpdate,
    BusinessLinkResponse,
    BusinessDetailsUpdate,
    SocialConnectRequest,
    SocialAccountItem,
    AiPhotoGenerateRequest,
    BusinessProfileComparisonResponse,
    SelectPlanRequest,
)
from app.services.business_onboarding_service import BusinessOnboardingService
from app.services.subscription_service import SubscriptionService
from app.core.database import get_database

router = APIRouter(prefix="/business-profile", tags=["Business Onboarding"])


def ensure_business_role(current_user: CurrentUser) -> None:
    role = current_user.role or current_user.get("accountType")
    if role and BusinessOnboardingService.normalize_role(role) != "business":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This endpoint is restricted to Business accounts only."
        )


# ── Step 1: Online Presence ──
@router.put("/online-presence", response_model=OnlinePresenceResponse)
async def update_online_presence(
    payload: OnlinePresenceRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    result = await BusinessOnboardingService.set_online_presence(
        current_user.id,
        payload.presence_types
    )
    return result


# ── Step 2: Business Links CRUD ──
@router.post("/links", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def add_link(
    payload: BusinessLinkCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    created_link = await BusinessOnboardingService.add_business_link(
        current_user.id,
        payload.type,
        payload.url,
        payload.platform
    )
    return {"success": True, "message": "Link added successfully", "data": created_link}


@router.get("/links", response_model=Dict[str, Any])
async def list_links(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    links = await BusinessOnboardingService.get_business_links(current_user.id)
    return {"success": True, "data": links}


@router.patch("/links/{link_id}", response_model=Dict[str, Any])
async def update_link(
    link_id: str,
    payload: BusinessLinkUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    updated = await BusinessOnboardingService.update_business_link(
        current_user.id,
        link_id,
        payload.model_dump(exclude_unset=True)
    )
    return {"success": True, "message": "Link updated successfully", "data": updated}


@router.delete("/links/{link_id}", response_model=Dict[str, Any])
async def delete_link(
    link_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    success = await BusinessOnboardingService.delete_business_link(current_user.id, link_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found or already deleted.")
    return {"success": True, "message": "Link deleted successfully"}


# ── Step 3: Website Auto-Fetch & Extracted Details ──
@router.post("/links/{link_id}/fetch", response_model=Dict[str, Any])
async def fetch_link_info(
    link_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    result = await BusinessOnboardingService.fetch_link_metadata(current_user.id, link_id)
    return result


@router.get("/links/{link_id}/fetch-status", response_model=Dict[str, Any])
async def get_fetch_status(
    link_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    links = await BusinessOnboardingService.get_business_links(current_user.id)
    target = next((l for l in links if l.get("link_id") == link_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found.")
    return {
        "success": True,
        "link_id": link_id,
        "status": target.get("fetch_status", "pending")
    }


@router.get("/extracted-details", response_model=Dict[str, Any])
async def get_extracted_details(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    draft = await BusinessOnboardingService.get_extracted_details(current_user.id)
    return {"success": True, "data": draft}


# ── Step 4: Business Details ──
@router.get("/details", response_model=Dict[str, Any])
async def get_details(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    db = get_database()
    profile = await db["business_profiles"].find_one({"user_id": current_user.id}) or {}
    return {"success": True, "data": profile.get("details", {})}


@router.patch("/details", response_model=Dict[str, Any])
@router.put("/details", response_model=Dict[str, Any])
async def update_details(
    payload: BusinessDetailsUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    updated = await BusinessOnboardingService.update_business_details(
        current_user.id,
        payload.model_dump(exclude_unset=True)
    )
    return {"success": True, "message": "Business details confirmed and saved", "data": updated}


# ── Step 5: Business Photos ──
@router.post("/photos", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_photo(
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    is_primary: bool = Form(False),
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)

    # Validate MIME type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: JPEG, PNG, WEBP."
        )

    # Directory
    upload_dir = os.path.join("uploads", "business_photos")
    os.makedirs(upload_dir, exist_ok=True)

    ext = os.path.splitext(file.filename)[1] or ".jpg"
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, safe_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_url = f"/uploads/business_photos/{safe_filename}"
    photo_entry = await BusinessOnboardingService.add_business_photo(
        current_user.id,
        file_url,
        caption=caption,
        is_primary=is_primary
    )

    return {"success": True, "message": "Photo uploaded successfully", "data": photo_entry}


@router.get("/photos", response_model=Dict[str, Any])
async def get_photos(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    photos = await BusinessOnboardingService.get_business_photos(current_user.id)
    return {"success": True, "data": photos}


@router.delete("/photos/{photo_id}", response_model=Dict[str, Any])
async def delete_photo(photo_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    success = await BusinessOnboardingService.delete_business_photo(current_user.id, photo_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found.")
    return {"success": True, "message": "Photo deleted successfully"}


# ── Step 6: Social Account Connections ──
@router.post("/social-accounts/connect", response_model=Dict[str, Any])
async def connect_social(
    payload: SocialConnectRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    result = await BusinessOnboardingService.connect_social_account(
        current_user.id,
        payload.platform,
        payload.access_token,
        account_id=payload.account_id,
        account_name=payload.account_name
    )
    return {"success": True, "message": f"{payload.platform.capitalize()} connected successfully", "data": result}


@router.get("/social-accounts", response_model=Dict[str, Any])
async def get_socials(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    accounts = await BusinessOnboardingService.get_social_accounts(current_user.id)
    return {"success": True, "data": accounts}


@router.delete("/social-accounts/{platform}", response_model=Dict[str, Any])
async def disconnect_social(platform: str, current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    success = await BusinessOnboardingService.disconnect_social_account(current_user.id, platform)
    return {"success": True, "message": f"{platform.capitalize()} disconnected successfully"}


# ── Step 7: AI Business Photos ──
@router.post("/ai-photos/generate", response_model=Dict[str, Any])
async def generate_ai_photos(
    payload: Optional[AiPhotoGenerateRequest] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_business_role(current_user)
    prompt = payload.prompt if payload else None
    style = payload.style if payload else "professional"
    result = await BusinessOnboardingService.generate_ai_photos(current_user.id, prompt=prompt, style=style)
    return result


@router.get("/ai-photos", response_model=Dict[str, Any])
async def get_ai_photos(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    db = get_database()
    profile = await db["business_profiles"].find_one({"user_id": current_user.id}) or {}
    return {"success": True, "data": profile.get("ai_photos", {})}


@router.post("/ai-photos/{photo_id}/save", response_model=Dict[str, Any])
async def save_ai_photo(photo_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    db = get_database()
    profile = await db["business_profiles"].find_one({"user_id": current_user.id}) or {}
    ai_data = profile.get("ai_photos", {})
    variations = ai_data.get("variations", [])
    target = next((v for v in variations if v.get("variation_id") == photo_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI variation photo not found.")

    photo_entry = await BusinessOnboardingService.add_business_photo(
        current_user.id,
        target.get("image_url"),
        caption=target.get("title")
    )
    return {"success": True, "message": "AI Photo saved to Business Photos", "data": photo_entry}


# ── Step 8: Profile Comparison ──
@router.get("/comparison", response_model=BusinessProfileComparisonResponse)
async def get_comparison(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    return await BusinessOnboardingService.get_profile_comparison(current_user.id)


# ── Step 10: Subscription ──
@router.get("/subscription", response_model=Dict[str, Any])
async def get_subscription(current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    sub = await BusinessOnboardingService.get_subscription_summary(current_user.id)
    return {"success": True, "data": sub}


@router.post("/subscription/select-plan", response_model=Dict[str, Any])
async def select_plan(payload: SelectPlanRequest, current_user: CurrentUser = Depends(get_current_user)):
    ensure_business_role(current_user)
    db = get_database()
    await db["subscriptions"].update_one(
        {"userId": current_user.id},
        {"$set": {
            "plan_id": payload.plan_id.upper(),
            "billing_cycle": payload.billing_cycle,
            "status": "active",
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    return {
        "success": True,
        "message": f"Plan '{payload.plan_id}' selected successfully.",
        "plan_id": payload.plan_id.upper(),
        "billing_cycle": payload.billing_cycle
    }
