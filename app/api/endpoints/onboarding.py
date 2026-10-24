from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from bson import ObjectId

from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.services.subscription_service import SubscriptionService
from app.services.auth_service import AuthService
from app.services.business_onboarding_service import BusinessOnboardingService
from app.schemas.onboarding_v2 import (
    RoleSelectRequest,
    RoleSelectResponse,
    OnboardingRatingRequest,
    OnboardingProgressResponse,
)

router = APIRouter()


# ── Section 3: Role Selection API ──
@router.post("/role", response_model=RoleSelectResponse)
async def select_onboarding_role(
    payload: RoleSelectRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Select account role during onboarding:
    - Exactly two roles supported: 'business' and 'influencer'.
    - Returns next step:
      * business -> 'online_presence'
      * influencer -> 'influencer_profile'
    """
    user_id = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)
    result = await BusinessOnboardingService.select_role(user_id, payload.role)
    return result


# ── Section 7: Onboarding Progress API ──
@router.get("/progress", response_model=OnboardingProgressResponse)
async def get_onboarding_progress(current_user: CurrentUser = Depends(get_current_user)):
    """
    Returns authenticated user's selected role, current step, completed steps,
    completion percentage, and next step dynamically derived from persisted state.
    """
    user_id = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)
    progress_data = await BusinessOnboardingService.calculate_progress(user_id)
    return progress_data


# ── Section 4 (Step 9): App Rating API ──
@router.post("/rating", response_model=Dict[str, Any])
async def submit_app_rating(
    payload: OnboardingRatingRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Optional app feedback and rating during onboarding.
    Skipping does not block onboarding progress.
    """
    user_id = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)
    result = await BusinessOnboardingService.submit_rating(
        user_id,
        payload.rating,
        payload.feedback,
        skipped=payload.skipped
    )
    return result


# ── Legacy Compatible Endpoints ──
@router.get("/status", response_model=Dict[str, Any])
async def get_onboarding_status(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    uid = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)

    # 1. Check business profile
    business = await BusinessService.get_business_by_owner(uid)
    business_completed = False
    if business:
        name = getattr(business, "businessName", None) or getattr(business, "name", None) or ""
        name = str(name).strip()
        if name and name != "My Business":
            business_completed = True

    # 2. Check social connections via token fields on user document
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)}) if ObjectId.is_valid(uid) else None
    if not user_doc and ObjectId.is_valid(uid):
        user_doc = await db["pending_users"].find_one({"_id": ObjectId(uid)})

    connected_platforms = []
    if user_doc:
        if user_doc.get("instagram_access_token"):
            connected_platforms.append("instagram")
        if user_doc.get("facebook_access_token"):
            connected_platforms.append("facebook")

    social_completed = len(connected_platforms) > 0

    # 3. Check subscription
    sub = await SubscriptionService.get_or_create_subscription(db, uid)

    onboarding_step = user_doc.get("onboarding_step", 1) if user_doc else 1
    if business_completed and onboarding_step == 1:
        is_pend = current_user.get("is_pending") if isinstance(current_user, dict) else getattr(current_user, "is_pending", False)
        coll = db["users"] if not is_pend else db["pending_users"]
        if ObjectId.is_valid(uid):
            await coll.update_one(
                {"_id": ObjectId(uid)},
                {"$set": {"onboarding_step": 2}}
            )
        onboarding_step = 2

    is_completed = bool(user_doc.get("onboardingCompleted", False)) if user_doc else False
    if not is_completed and user_doc and user_doc.get("onboarding_completed_at"):
        is_completed = True

    is_pending_val = current_user.get("is_pending", False) if isinstance(current_user, dict) else getattr(current_user, "is_pending", False)

    return {
        "onboarding_completed": is_completed,
        "onboardingCompleted": is_completed,
        "is_completed": is_completed,
        "is_pending": is_pending_val,
        "business_profile_completed": business_completed,
        "social_connection_completed": social_completed,
        "connected_platforms": connected_platforms,
        "onboarding_step": onboarding_step,
        "subscription_status": sub.get("status", "free"),
        "selected_plan_id": sub.get("plan_id", "FREE"),
        "onboarding_completed_at": user_doc.get("onboarding_completed_at") if user_doc else None
    }


@router.patch("/progress", response_model=Dict[str, Any])
async def update_onboarding_progress(payload: Dict[str, Any], current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    uid = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)

    allowed_fields = {"onboarding_step", "business_profile_completed", "social_connection_completed"}
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}

    if update_data:
        if update_data.get("social_connection_completed") or update_data.get("business_profile_completed"):
            update_data["onboarding_completed_at"] = datetime.now(timezone.utc).isoformat()
            update_data["onboardingCompleted"] = True
            await AuthService.commit_pending_user(uid, update_data)
        else:
            is_pend = current_user.get("is_pending") if isinstance(current_user, dict) else getattr(current_user, "is_pending", False)
            coll = db["pending_users"] if is_pend else db["users"]
            if ObjectId.is_valid(uid):
                await coll.update_one(
                    {"_id": ObjectId(uid)},
                    {"$set": update_data}
                )

    return {"success": True, "message": "Onboarding progress updated"}


@router.post("/complete", response_model=Dict[str, Any])
async def complete_onboarding(payload: Dict[str, Any] = None, current_user: CurrentUser = Depends(get_current_user)):
    """Explicitly finalize onboarding and commit user from pending_users to users collection."""
    uid = str(current_user["id"] if isinstance(current_user, dict) else current_user.id)
    extra_data = payload or {}
    extra_data["onboardingCompleted"] = True
    user_doc = await AuthService.commit_pending_user(uid, extra_data)
    if not user_doc:
        raise HTTPException(status_code=404, detail="Failed to finalize onboarding user")
        
    user_doc["id"] = str(user_doc["_id"])
    del user_doc["_id"]
    return {
        "success": True,
        "message": "Onboarding completed successfully. Account is now active in database.",
        "data": user_doc
    }
