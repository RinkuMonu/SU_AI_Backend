from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.core.billing_config import PLANS

router = APIRouter(
    prefix="/subscription",
    tags=["Subscription"]
)

class UpgradeRequest(BaseModel):
    plan_id: str

@router.get("/plans")
async def get_plans():
    return {"success": True, "data": PLANS}

@router.get("/me")
async def get_my_subscription(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    sub = await SubscriptionService.get_or_create_subscription(db, str(current_user["id"]))
    
    # Get current month usage
    from datetime import datetime, timezone
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = await db["usage"].find_one({"user_id": str(current_user["id"]), "month": current_month})
    
    if not usage:
        usage = {"posts_created": 0, "reels_created": 0}
        
    sub["usage"] = usage
    sub["plan_details"] = PLANS.get(sub.get("plan_id", "FREE"), PLANS["FREE"])
    
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
    if request.plan_id not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
        
    # Mock checkout process
    return {"success": True, "message": "Proceed to payment", "plan_id": request.plan_id}

@router.post("/upgrade")
async def upgrade_subscription(
    request: UpgradeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    # Mocking payment verification
    updated = await SubscriptionService.upgrade_plan(db, str(current_user["id"]), request.plan_id)
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
