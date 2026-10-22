from fastapi import Depends, HTTPException, status
from app.core.security import get_current_user, require_role, require_businessman, require_influencer
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.core.billing_config import FEATURE_PRICING

def _get_user_id(current_user) -> str:
    if isinstance(current_user, dict):
        return str(current_user.get("id") or current_user.get("_id") or "")
    return str(getattr(current_user, "id", "") or "")

def require_feature(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        user_id = _get_user_id(current_user)
        await SubscriptionService.check_feature_access(db, user_id, feature_name)
        return current_user
    return dependency

def require_credits(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        user_id = _get_user_id(current_user)
        cost = FEATURE_PRICING.get(feature_name, 1)
        await CreditService.check_credits(db, user_id, feature_name)
        return current_user
    return dependency

def require_usage_limit(feature_type: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        user_id = _get_user_id(current_user)
        await SubscriptionService.check_usage_limit(db, user_id, feature_type)
        return current_user
    return dependency

def require_plan(min_plan: str):
    # For a robust implementation, plans should have a hierarchy score.
    # We will simply check if they are exactly on the plan or we can assume it's just a placeholder for now
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        user_id = _get_user_id(current_user)
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        if sub.get("plan_id") != min_plan:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PLAN_REQUIRED: This action requires the {min_plan} plan."
            )
        return current_user
    return dependency
