from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.credit_service import CreditService
from app.schemas.credit import CreditBalanceResponse, CreditHistoryResponse
from app.core.billing_config import FEATURE_PRICING, PLANS

router = APIRouter(
    prefix="/api/v1/credits",
    tags=["Credits"]
)

class CreditDeductRequest(BaseModel):
    action: str = Field(..., description="Action/feature to deduct credits for, e.g. ai_image, ai_post, ai_reel")
    description: Optional[str] = None

@router.get("/me", response_model=CreditBalanceResponse)
async def get_my_credits(
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    # This automatically provisions the FREE plan for existing users who don't have one
    uid = str(current_user.id if hasattr(current_user, "id") else (current_user.get("id") or current_user.get("_id")))
    sub = await CreditService.get_or_create_subscription(db, uid)
    
    total = sub.get("credits_total", 50)
    remaining = sub.get("credits_remaining", 50)
    used = max(0, total - remaining)
    
    return {
        "plan": sub.get("plan", "FREE"),
        "credits_total": total,
        "credits_remaining": remaining,
        "credits_used": used
    }

@router.get("/pricing")
async def get_credit_pricing():
    return {
        "success": True,
        "feature_pricing": FEATURE_PRICING,
        "plans": {
            k: {
                "name": v.get("name"),
                "price": v.get("price"),
                "credits": v.get("credits"),
                "credits_badge": v.get("credits_badge"),
                "features": v.get("features", []),
            }
            for k, v in PLANS.items()
        }
    }

@router.post("/deduct")
async def deduct_my_credits(
    payload: CreditDeductRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    uid = str(current_user.id if hasattr(current_user, "id") else (current_user.get("id") or current_user.get("_id")))
    action = payload.action.strip()
    cost = FEATURE_PRICING.get(action, 1)

    result = await CreditService.deduct_credits(db, uid, action)
    sub = await CreditService.get_or_create_subscription(db, uid)

    total = sub.get("credits_total", 50)
    remaining = sub.get("credits_remaining", 0)
    used = max(0, total - remaining)

    return {
        "success": True,
        "action": action,
        "cost": cost,
        "credits_remaining": remaining,
        "credits_total": total,
        "credits_used": used,
    }

@router.get("/history", response_model=CreditHistoryResponse)
async def get_my_history(
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    uid = str(current_user.id if hasattr(current_user, "id") else (current_user.get("id") or current_user.get("_id")))
    history = await CreditService.get_history(db, uid)
    return {"transactions": history}
