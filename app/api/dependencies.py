from fastapi import Depends, HTTPException, status
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.core.billing_config import FEATURE_PRICING

def _extract_user_id(current_user) -> str:
    if hasattr(current_user, "id"):
        return str(current_user.id)
    if isinstance(current_user, dict):
        return str(current_user.get("id") or current_user.get("_id"))
    return str(current_user)

def require_feature(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        uid = _extract_user_id(current_user)
        await SubscriptionService.check_feature_access(db, uid, feature_name)
        return current_user
    return dependency

def require_credits(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        uid = _extract_user_id(current_user)
        cost = FEATURE_PRICING.get(feature_name, 1)
        await CreditService.check_credits(db, uid, feature_name)
        return current_user
    return dependency

def require_usage_limit(feature_type: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        uid = _extract_user_id(current_user)
        await SubscriptionService.check_usage_limit(db, uid, feature_type)
        return current_user
    return dependency

def require_plan(min_plan: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        uid = _extract_user_id(current_user)
        sub = await SubscriptionService.get_or_create_subscription(db, uid)
        if sub.get("plan_id") != min_plan:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PLAN_REQUIRED: This action requires the {min_plan} plan."
            )
        return current_user
    return dependency
