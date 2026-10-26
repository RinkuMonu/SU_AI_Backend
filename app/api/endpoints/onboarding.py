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
from app.services.brand_service import BrandService
from app.services.social_connectivity_service import SocialConnectivityService
from app.services.plan_onboarding_service import PlanOnboardingService

@router.get("/status", response_model=Dict[str, Any])
async def get_onboarding_status(current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))

    # 1. Check business profile & Brand Kit (Step 1)
    business = await BusinessService.get_business_by_owner(uid)
    business_doc = await db["businesses"].find_one({"owner_id": uid})
    brand_status = await BrandService.get_onboarding_status(db, current_user)
    
    brand_kit_completed = brand_status.brand_kit_completed
    brand_kit_status_str = brand_status.brand_kit_status
    brand_kit_pct = brand_status.completion_percentage
    is_brand_dismissed = bool(
        getattr(brand_status, "brand_kit_dismissed", False) or
        (brand_status.brand_kit and brand_status.brand_kit.get("brand_kit_dismissed", False)) or
        (business_doc and business_doc.get("brand_kit_dismissed", False))
    )

    # Legacy business profile flag
    business_completed = brand_kit_completed or (brand_kit_pct > 0)
    if not business_completed and business:
        name = getattr(business, "businessName", None) or getattr(business, "name", None) or ""
        name = str(name).strip()
        if name and name != "My Business":
            business_completed = True

    # 2. Social Media Connectivity (Step 2)
    social_status = await SocialConnectivityService.get_social_onboarding_status(db, current_user)
    is_social_completed = social_status.social_connectivity_completed
    is_social_skipped = bool(
        (business_doc and business_doc.get("social_connectivity_skipped", False)) or
        current_user.get("social_connectivity_skipped", False)
    )
    
    connected_platforms = [p for p, info in social_status.platforms.items() if info.connected]
    # Also check user doc access tokens for fallback
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    if not user_doc:
        user_doc = await db["pending_users"].find_one({"_id": ObjectId(uid)})
    if user_doc:
        if user_doc.get("instagram_access_token") and "instagram" not in connected_platforms:
            connected_platforms.append("instagram")
        if user_doc.get("facebook_access_token") and "facebook" not in connected_platforms:
            connected_platforms.append("facebook")
    if connected_platforms:
        is_social_completed = True

    # 3. Subscription Plan (Step 3)
    plan_status = await PlanOnboardingService.get_plan_onboarding_status(db, current_user)
    sub = await SubscriptionService.get_or_create_subscription(db, uid)
    is_plan_completed = plan_status.plan_activation_completed
    is_plan_skipped = bool(
        (business_doc and business_doc.get("plan_selection_skipped", False)) or
        current_user.get("plan_selection_skipped", False)
    )

    # Determine recommended next action and modal
    current_modal = None
    if brand_status.should_show_modal:
        current_modal = "brand_kit"
        next_action = "Save your Brand Kit branding details"
    elif social_status.should_show_modal:
        current_modal = "social_connectivity"
        next_action = "Connect at least one social media account, or skip to continue"
    elif plan_status.should_show_modal:
        current_modal = "subscription_plan"
        next_action = "Select or activate your subscription plan"
    else:
        current_modal = None
        next_action = "Onboarding completed. Explore your AI workspace"

    # Overall completion percentage
    step1_weight = 40.0 * (brand_kit_pct / 100.0)
    step2_weight = 30.0 if (is_social_completed or is_social_skipped) else 0.0
    step3_weight = 30.0 if (is_plan_completed or is_plan_skipped) else 0.0
    overall_pct = int(round(step1_weight + step2_weight + step3_weight))

    onboarding_step = user_doc.get("onboarding_step", 1) if user_doc else 1
    if business_completed and onboarding_step == 1:
        onboarding_step = 2
    if (is_social_completed or is_social_skipped) and onboarding_step == 2:
        onboarding_step = 3

    is_overall_completed = bool(
        user_doc.get("onboardingCompleted", False) or
        user_doc.get("onboarding_completed_at") or
        (business_completed and (is_social_completed or is_social_skipped) and (is_plan_completed or is_plan_skipped))
    )

    return {
        # Legacy compatibility keys
        "onboarding_completed": is_overall_completed,
        "onboardingCompleted": is_overall_completed,
        "is_completed": is_overall_completed,
        "is_pending": current_user.get("is_pending", False),
        "business_profile_completed": business_completed,
        "social_connection_completed": is_social_completed,
        "connected_platforms": connected_platforms,
        "onboarding_step": onboarding_step,
        "subscription_status": sub.get("status", "free"),
        "selected_plan_id": sub.get("plan_id", "FREE"),
        "onboarding_completed_at": user_doc.get("onboarding_completed_at") if user_doc else None,

        # Three-step persistent status structure
        "overall_completion_percentage": overall_pct,
        "next_recommended_action": next_action,
        "current_modal_to_show": current_modal,
        "steps": {
            "step_1_brand_kit": {
                "status": "completed" if brand_kit_completed else ("in_progress" if brand_kit_pct > 0 else "not_started"),
                "is_completed": brand_kit_completed,
                "is_dismissed": is_brand_dismissed,
                "completion_percentage": brand_kit_pct,
                "completed_sections": brand_status.completed_sections,
                "pending_sections": brand_status.pending_sections,
                "should_show_modal": brand_status.should_show_modal
            },
            "step_2_social_connectivity": {
                "status": "completed" if is_social_completed else ("skipped" if is_social_skipped else "pending"),
                "is_completed": is_social_completed,
                "is_skipped": is_social_skipped,
                "connected_count": len(connected_platforms),
                "connected_platforms": connected_platforms,
                "should_show_modal": social_status.should_show_modal
            },
            "step_3_subscription_plan": {
                "status": "completed" if is_plan_completed else ("skipped" if is_plan_skipped else "pending"),
                "is_completed": is_plan_completed,
                "is_skipped": is_plan_skipped,
                "is_eligible": plan_status.is_eligible,
                "active_plan": plan_status.active_plan.dict() if plan_status.active_plan else None,
                "should_show_modal": plan_status.should_show_modal
            }
        }
    }


@router.patch("/progress", response_model=Dict[str, Any])
async def update_onboarding_progress(payload: Dict[str, Any], current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))
    now = datetime.now(timezone.utc)

    allowed_fields = {
        "onboarding_step",
        "business_profile_completed",
        "social_connection_completed",
        "brand_kit_dismissed",
        "social_connectivity_skipped",
        "social_skipped",
        "plan_selection_skipped",
        "plan_skipped"
    }
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}

    # Normalize skipped keys
    if "social_skipped" in update_data:
        update_data["social_connectivity_skipped"] = update_data.pop("social_skipped")
    if "plan_skipped" in update_data:
        update_data["plan_selection_skipped"] = update_data.pop("plan_skipped")

    if update_data:
        # Also update business doc for persistent onboarding state
        business_updates = {}
        if "social_connectivity_skipped" in update_data:
            business_updates["social_connectivity_skipped"] = update_data["social_connectivity_skipped"]
            business_updates["social_connectivity_skipped_at"] = now
        if "plan_selection_skipped" in update_data:
            business_updates["plan_selection_skipped"] = update_data["plan_selection_skipped"]
            business_updates["plan_selection_skipped_at"] = now
        if "brand_kit_dismissed" in update_data:
            business_updates["brand_kit_dismissed"] = update_data["brand_kit_dismissed"]
            business_updates["brand_kit_dismissed_at"] = now

        if business_updates:
            business_updates["updated_at"] = now
            await db["businesses"].update_one(
                {"owner_id": uid},
                {"$set": business_updates},
                upsert=True
            )

        if update_data.get("social_connection_completed") or update_data.get("business_profile_completed"):
            update_data["onboarding_completed_at"] = now.isoformat()
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
