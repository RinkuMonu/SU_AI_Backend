from fastapi import Depends, HTTPException, status
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.core.billing_config import FEATURE_PRICING

def require_feature(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        await SubscriptionService.check_feature_access(db, str(current_user["_id"]), feature_name)
        return current_user
    return dependency

def require_credits(feature_name: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        cost = FEATURE_PRICING.get(feature_name, 1)
        await CreditService.check_credits(db, str(current_user["_id"]), feature_name)
        return current_user
    return dependency

def require_usage_limit(feature_type: str):
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        await SubscriptionService.check_usage_limit(db, str(current_user["_id"]), feature_type)
        return current_user
    return dependency

def require_plan(min_plan: str):
    # For a robust implementation, plans should have a hierarchy score.
    # We will simply check if they are exactly on the plan or we can assume it's just a placeholder for now
    async def dependency(current_user=Depends(get_current_user), db=Depends(get_database)):
        sub = await SubscriptionService.get_or_create_subscription(db, str(current_user["_id"]))
        if sub.get("plan_id") != min_plan:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PLAN_REQUIRED: This action requires the {min_plan} plan."
            )
        return current_user
    return dependency
