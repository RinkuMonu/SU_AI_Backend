from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.services.subscription_service import SubscriptionService
from datetime import datetime, timezone
from bson import ObjectId

router = APIRouter()


from app.services.auth_service import AuthService

@router.get("/status", response_model=Dict[str, Any])
async def get_onboarding_status(current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))

    # 1. Check business profile
    business = await BusinessService.get_business_by_owner(uid)
    business_completed = False
    if business:
        name = getattr(business, "businessName", None) or getattr(business, "name", None) or ""
        name = str(name).strip()
        if name and name != "My Business":
            business_completed = True

    # 2. Check social connections via token fields on user document
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    if not user_doc:
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
    # Auto-advance step: if business done and step is still 1, move to 2
    if business_completed and onboarding_step == 1:
        coll = db["users"] if not current_user.get("is_pending") else db["pending_users"]
        await coll.update_one(
            {"_id": ObjectId(uid)},
            {"$set": {"onboarding_step": 2}}
        )
        onboarding_step = 2

    is_completed = bool(user_doc.get("onboardingCompleted", False)) if user_doc else False
    if not is_completed and user_doc and user_doc.get("onboarding_completed_at"):
        is_completed = True

    return {
        "onboarding_completed": is_completed,
        "onboardingCompleted": is_completed,
        "is_completed": is_completed,
        "is_pending": current_user.get("is_pending", False),
        "business_profile_completed": business_completed,
        "social_connection_completed": social_completed,
        "connected_platforms": connected_platforms,
        "onboarding_step": onboarding_step,
        "subscription_status": sub.get("status", "free"),
        "selected_plan_id": sub.get("plan_id", "FREE"),
        "onboarding_completed_at": user_doc.get("onboarding_completed_at") if user_doc else None
    }


@router.patch("/progress", response_model=Dict[str, Any])
async def update_onboarding_progress(payload: Dict[str, Any], current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))

    allowed_fields = {"onboarding_step", "business_profile_completed", "social_connection_completed"}
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}

    if update_data:
        if update_data.get("social_connection_completed") or update_data.get("business_profile_completed"):
            update_data["onboarding_completed_at"] = datetime.now(timezone.utc).isoformat()
            update_data["onboardingCompleted"] = True
            await AuthService.commit_pending_user(uid, update_data)
        else:
            coll = db["pending_users"] if current_user.get("is_pending") else db["users"]
            await coll.update_one(
                {"_id": ObjectId(uid)},
                {"$set": update_data}
            )

    return {"success": True, "message": "Onboarding progress updated"}


@router.post("/complete", response_model=Dict[str, Any])
async def complete_onboarding(payload: Dict[str, Any] = None, current_user=Depends(get_current_user)):
    """Explicitly finalize onboarding and commit user from pending_users to users collection."""
    uid = str(current_user.get("id"))
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
