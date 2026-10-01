from datetime import datetime, timezone
from fastapi import HTTPException, status
from pymongo.collection import ReturnDocument
from app.core.billing_config import PLANS

class SubscriptionService:
    @staticmethod
    async def get_or_create_subscription(db, user_id: str):
        collection = db["subscriptions"]
        existing = await collection.find_one({"user_id": user_id})
        
        if existing:
            return existing
            
        now = datetime.now(timezone.utc)
        default_plan_id = "FREE"
        plan_config = PLANS[default_plan_id]
        
        new_sub = {
            "user_id": user_id,
            "plan_id": default_plan_id,
            "plan": default_plan_id, # for backwards compatibility
            "credits_total": plan_config["credits"],
            "credits_remaining": plan_config["credits"],
            "status": "active",
            "start_date": now,
            "created_at": now,
            "updated_at": now
        }
        
        try:
            result = await collection.find_one_and_update(
                {"user_id": user_id},
                {"$setOnInsert": new_sub},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            return result
        except Exception:
            return await collection.find_one({"user_id": user_id})

    @staticmethod
    async def check_feature_access(db, user_id: str, feature_name: str):
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        plan_id = sub.get("plan_id", "FREE")
        plan_config = PLANS.get(plan_id, PLANS["FREE"])
        
        if feature_name not in plan_config.get("features", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"FEATURE_NOT_AVAILABLE: '{feature_name}' is not available on the {plan_id} plan."
            )
        return True

    @staticmethod
    async def check_usage_limit(db, user_id: str, feature_type: str):
        """feature_type can be 'post' or 'reel'"""
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        plan_id = sub.get("plan_id", "FREE")
        plan_config = PLANS.get(plan_id, PLANS["FREE"])
        
        limit = plan_config.get(f"{feature_type}_limit", -1)
        if limit == -1:
            return True # Unlimited
            
        # Get current month usage
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage_col = db["usage"]
        usage = await usage_col.find_one({"user_id": user_id, "month": current_month})
        
        current_usage = 0
        if usage:
            current_usage = usage.get(f"{feature_type}s_created", 0)
            
        if current_usage >= limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"USAGE_LIMIT_REACHED: You have reached your monthly limit of {limit} {feature_type}s."
            )
        return True

    @staticmethod
    async def increment_usage(db, user_id: str, feature_type: str):
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage_col = db["usage"]
        
        await usage_col.update_one(
            {"user_id": user_id, "month": current_month},
            {"$inc": {f"{feature_type}s_created": 1}, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True
        )

    @staticmethod
    async def upgrade_plan(db, user_id: str, new_plan_id: str):
        if new_plan_id not in PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan")
            
        plan_config = PLANS[new_plan_id]
        collection = db["subscriptions"]
        
        # We assume immediate activation for this mock
        now = datetime.now(timezone.utc)
        
        updated = await collection.find_one_and_update(
            {"user_id": user_id},
            {
                "$set": {
                    "plan_id": new_plan_id,
                    "plan": new_plan_id,
                    "updated_at": now
                },
                "$inc": {
                    "credits_remaining": plan_config["credits"],
                    "credits_total": plan_config["credits"]
                }
            },
            return_document=ReturnDocument.AFTER
        )
        return updated
