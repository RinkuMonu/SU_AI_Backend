from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.services.subscription_service import SubscriptionService
from datetime import datetime, timezone
from bson import ObjectId

router = APIRouter()


@router.get("/status", response_model=Dict[str, Any])
async def get_onboarding_status(current_user=Depends(get_current_user)):
    db = get_database()

    # 1. Check business profile
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    business_completed = business is not None

    # 2. Check social connections via token fields on user document
    user_doc = await db["users"].find_one({"_id": ObjectId(str(current_user.id))})

    connected_platforms = []
    if user_doc:
        if user_doc.get("instagram_access_token"):
            connected_platforms.append("instagram")
        if user_doc.get("facebook_access_token"):
            connected_platforms.append("facebook")
        if user_doc.get("whatsapp_access_token"):
            connected_platforms.append("whatsapp")

    social_completed = len(connected_platforms) > 0

    # 3. Check subscription
    sub = await SubscriptionService.get_or_create_subscription(db, str(current_user.id))

    onboarding_step = user_doc.get("onboarding_step", 1) if user_doc else 1
    # Auto-advance step: if business done and step is still 1, move to 2
    if business_completed and onboarding_step == 1:
        await db["users"].update_one(
            {"_id": ObjectId(str(current_user.id))},
            {"$set": {"onboarding_step": 2}}
        )
        onboarding_step = 2

    return {
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

    allowed_fields = {"onboarding_step", "business_profile_completed", "social_connection_completed"}
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}

    if update_data:
        if update_data.get("social_connection_completed"):
            update_data["onboarding_completed_at"] = datetime.now(timezone.utc).isoformat()

        await db["users"].update_one(
            {"_id": ObjectId(str(current_user.id))},
            {"$set": update_data}
        )

    return {"success": True, "message": "Onboarding progress updated"}
