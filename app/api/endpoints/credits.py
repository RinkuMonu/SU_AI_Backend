from fastapi import APIRouter, Depends
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.credit_service import CreditService
from app.schemas.credit import CreditBalanceResponse, CreditHistoryResponse

router = APIRouter(
    prefix="/api/v1/credits",
    tags=["Credits"]
)

@router.get("/me", response_model=CreditBalanceResponse)
async def get_my_credits(
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    # This automatically provisions the FREE plan for existing users who don't have one
    sub = await CreditService.get_or_create_subscription(db, current_user.id)
    
    total = sub.get("credits_total", 50)
    remaining = sub.get("credits_remaining", 50)
    used = total - remaining
    
    return {
        "plan": sub.get("plan", "FREE"),
        "credits_total": total,
        "credits_remaining": remaining,
        "credits_used": used
    }

@router.get("/history", response_model=CreditHistoryResponse)
async def get_my_history(
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    history = await CreditService.get_history(db, current_user.id)
    return {"transactions": history}
