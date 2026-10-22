from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.services.plan_onboarding_service import PlanOnboardingService
from app.schemas.billing_onboarding import PlanOnboardingStatusResponse
from app.core.billing_config import PLANS, BILLING_CYCLES, get_formatted_plans

router = APIRouter(
    prefix="/subscription",
    tags=["Subscription"]
)

class UpgradeRequest(BaseModel):
    plan_id: str
    billing_cycle: Optional[str] = "monthly"

@router.get("/onboarding-status", response_model=PlanOnboardingStatusResponse)
async def get_plan_onboarding_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns Step 3: Plan Selection and Activation onboarding status.
    Determines if the plan popup should open based on:
    1. Brand Kit completed (Step 1)
    2. At least one social media account connected (Step 2)
    3. No qualifying plan active (Step 3 incomplete)
    """
    return await PlanOnboardingService.get_plan_onboarding_status(db, current_user)

@router.get("/plans")
async def get_plans(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    user_id = str(current_user.get("id") or current_user.get("_id"))
    sub = await SubscriptionService.get_or_create_subscription(db, user_id)
    active_plan_id = sub.get("plan_id", "FREE")
    formatted = get_formatted_plans(active_plan_id)
    return {
        "success": True,
        "data": PLANS,
        "plans_list": formatted,
        "billing_cycles": BILLING_CYCLES
    }

@router.get("/available-plans")
async def get_available_plans_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    user_id = str(current_user.get("id") or current_user.get("_id"))
    sub = await SubscriptionService.get_or_create_subscription(db, user_id)
    active_plan_id = sub.get("plan_id", "FREE")
    return {
        "success": True,
        "data": get_formatted_plans(active_plan_id),
        "billing_cycles": BILLING_CYCLES
    }

@router.get("/me")
async def get_my_subscription(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    user_id = str(current_user["id"])
    sub = await SubscriptionService.get_or_create_subscription(db, user_id)
    
    # Get current month usage
    from datetime import datetime, timezone
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = await db["usage"].find_one({"user_id": user_id, "month": current_month})
    
    if not usage:
        usage = {"posts_created": 0, "reels_created": 0}
        
    sub["usage"] = usage
    sub["plan_details"] = PLANS.get(sub.get("plan_id", "FREE"))
    
    # Check business plan onboarding completion
    business = await db["businesses"].find_one({"owner_id": user_id})
    sub["plan_activation_completed"] = bool(business and business.get("plan_activation_completed", False))
    
    # Exclude _id to avoid serialization issues
    if "_id" in sub:
        sub["id"] = str(sub.pop("_id"))
    if "_id" in sub["usage"]:
        del sub["usage"]["_id"]
        
    return {"success": True, "data": sub}

@router.post("/checkout")
async def checkout(
    request: UpgradeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    normalized = request.plan_id.upper().strip()
    if normalized not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
        
    # Return checkout metadata
    return {
        "success": True,
        "message": "Proceed to payment",
        "plan_id": normalized,
        "billing_cycle": request.billing_cycle or "monthly"
    }

@router.post("/upgrade")
async def upgrade_subscription(
    request: UpgradeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    updated = await SubscriptionService.upgrade_plan(
        db, str(current_user["id"]), request.plan_id, billing_cycle=request.billing_cycle or "monthly"
    )
    if "_id" in updated:
        updated["id"] = str(updated.pop("_id"))
    return {"success": True, "message": f"Upgraded to {request.plan_id} successfully", "data": updated}

@router.get("/credits")
async def get_credits(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    sub = await SubscriptionService.get_or_create_subscription(db, str(current_user["id"]))
    return {"success": True, "credits_remaining": sub.get("credits_remaining", 0)}

@router.get("/credits/transactions")
async def get_credit_transactions(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    history = await CreditService.get_history(db, str(current_user["id"]))
    return {"success": True, "data": history}

