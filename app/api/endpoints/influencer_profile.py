from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.schemas.onboarding_v2 import (
    InfluencerDetailsUpdate,
    InfluencerMediaKitRequest,
    SocialConnectRequest,
)
from app.services.business_onboarding_service import BusinessOnboardingService

router = APIRouter(prefix="/influencer-profile", tags=["Influencer Profile"])
legacy_router = APIRouter(prefix="/influencer/profile", tags=["Influencer Profile (Legacy)"])


def ensure_influencer_role(current_user: CurrentUser) -> None:
    role = current_user.role or current_user.get("accountType")
    if role and BusinessOnboardingService.normalize_role(role) != "influencer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This endpoint is restricted to Influencer accounts only."
        )


@router.get("/me", response_model=Dict[str, Any])
@legacy_router.get("/me", response_model=Dict[str, Any])
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    ensure_influencer_role(current_user)
    db = get_database()
    profile_doc = await db["influencer_profiles"].find_one({"user_id": current_user.id})

    if not profile_doc:
        return {"success": True, "data": None}

    profile_doc["id"] = str(profile_doc.pop("_id", current_user.id))
    return {"success": True, "data": profile_doc}


@router.patch("/details", response_model=Dict[str, Any])
@router.put("/details", response_model=Dict[str, Any])
@legacy_router.put("/me", response_model=Dict[str, Any])
async def update_my_profile(
    profile_data: InfluencerDetailsUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_influencer_role(current_user)
    db = get_database()
    update_dict = profile_data.model_dump(exclude_unset=True)
    update_dict["user_id"] = current_user.id
    update_dict["updated_at"] = datetime.now(timezone.utc)

    # Sync display name / niche
    if "creator_name" in update_dict:
        update_dict["username"] = update_dict["creator_name"]
        update_dict["display_name"] = update_dict["creator_name"]

    await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$set": update_dict},
        upsert=True
    )

    # Sync to users collection
    user_sync = {}
    if "creator_name" in update_dict:
        user_sync["name"] = update_dict["creator_name"]
    if "profile_photo_url" in update_dict:
        user_sync["profileImageUrl"] = update_dict["profile_photo_url"]
    if user_sync:
        user_oid = ObjectId(current_user.id) if ObjectId.is_valid(current_user.id) else current_user.id
        await db["users"].update_one({"$or": [{"_id": user_oid}, {"id": current_user.id}]}, {"$set": user_sync})

    updated = await db["influencer_profiles"].find_one({"user_id": current_user.id})
    updated["id"] = str(updated.pop("_id", current_user.id))
    return {"success": True, "message": "Influencer details updated successfully", "data": updated}


@router.post("/social-accounts/connect", response_model=Dict[str, Any])
async def connect_social_account(
    payload: SocialConnectRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_influencer_role(current_user)
    db = get_database()

    account_entry = {
        "platform": payload.platform.lower(),
        "account_id": payload.account_id,
        "account_name": payload.account_name,
        "connected": True,
        "connected_at": datetime.now(timezone.utc)
    }

    await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$pull": {"social_accounts": {"platform": payload.platform.lower()}}}
    )
    await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$push": {"social_accounts": account_entry}},
        upsert=True
    )

    return {"success": True, "message": f"{payload.platform.capitalize()} connected successfully", "data": account_entry}


@router.get("/social-accounts", response_model=Dict[str, Any])
async def get_social_accounts(current_user: CurrentUser = Depends(get_current_user)):
    ensure_influencer_role(current_user)
    db = get_database()
    profile = await db["influencer_profiles"].find_one({"user_id": current_user.id})
    return {"success": True, "data": profile.get("social_accounts", []) if profile else []}


@router.delete("/social-accounts/{platform}", response_model=Dict[str, Any])
async def disconnect_social_account(platform: str, current_user: CurrentUser = Depends(get_current_user)):
    ensure_influencer_role(current_user)
    db = get_database()
    res = await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$pull": {"social_accounts": {"platform": platform.lower()}}}
    )
    return {"success": True, "message": f"{platform.capitalize()} disconnected successfully"}


@router.post("/media-kit", response_model=Dict[str, Any])
async def save_media_kit(
    payload: InfluencerMediaKitRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    ensure_influencer_role(current_user)
    db = get_database()
    media_kit_data = payload.model_dump(exclude_unset=True)
    media_kit_data["updated_at"] = datetime.now(timezone.utc)

    await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$set": {"media_kit": media_kit_data}},
        upsert=True
    )

    return {"success": True, "message": "Media kit saved successfully", "data": media_kit_data}


@router.get("/completion", response_model=Dict[str, Any])
async def get_influencer_completion(current_user: CurrentUser = Depends(get_current_user)):
    ensure_influencer_role(current_user)
    progress = await BusinessOnboardingService.calculate_progress(current_user.id)
    return {
        "success": True,
        "completion_percentage": progress["completion_percentage"],
        "completed_steps": progress["completed_steps"],
        "current_step": progress["current_step"],
        "next_step": progress["next_step"],
        "is_completed": progress["is_completed"]
    }


# Legacy portfolio endpoint compatibility
@legacy_router.post("/me/portfolio")
async def add_portfolio_item(item: dict, current_user: CurrentUser = Depends(get_current_user)):
    ensure_influencer_role(current_user)
    db = get_database()
    item["created_at"] = datetime.now(timezone.utc)
    result = await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$push": {"portfolio": item}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Profile not found. Please setup profile first.")
    return {"success": True, "message": "Portfolio updated"}
