from datetime import datetime, timezone
from fastapi import HTTPException, status
from pymongo.collection import ReturnDocument
from bson import ObjectId
from app.core.billing_config import FEATURE_PRICING

class CreditService:
    @staticmethod
    async def get_or_create_subscription(db, user_id: str):
        from app.services.subscription_service import SubscriptionService
        return await SubscriptionService.get_or_create_subscription(db, user_id)

    @staticmethod
    async def check_credits(db, user_id: str, action: str):
        """Check if user has enough credits without deducting. Raises 402 if not."""
        from app.core.config import settings
        is_dev = getattr(settings, "ENVIRONMENT", "development") == "development"
        has_custom_key = bool(getattr(settings, "GEMINI_API_KEY", None))

        sub = await CreditService.get_or_create_subscription(db, user_id)
        cost = FEATURE_PRICING.get(action, 1)

        if sub.get("credits_remaining", 0) < cost:
            if is_dev or has_custom_key:
                # Auto-replenish in development or when custom Gemini API key is configured
                sub_collection = db["subscriptions"]
                await sub_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "credits_remaining": 1000,
                            "credits_total": 1000,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
                return True
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"INSUFFICIENT_CREDITS: Required {cost}, Remaining: {sub.get('credits_remaining', 0)}",
            )
        return True

    @staticmethod
    async def deduct_credits(db, user_id: str, action: str) -> dict:
        """Atomically deducts credits for an action and logs the transaction. Raises 402 if insufficient."""
        from app.core.config import settings
        is_dev = getattr(settings, "ENVIRONMENT", "development") == "development"
        has_custom_key = bool(getattr(settings, "GEMINI_API_KEY", None))

        cost = FEATURE_PRICING.get(action, 1)

        if cost == 0:
            return {"success": True}

        # Ensure subscription exists
        await CreditService.get_or_create_subscription(db, user_id)

        # Atomic deduction using $gte to prevent negative balance
        sub_collection = db["subscriptions"]
        updated_sub = await sub_collection.find_one_and_update(
            {
                "user_id": user_id,
                "credits_remaining": {"$gte": cost},
            },
            {
                "$inc": {"credits_remaining": -cost},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )

        if not updated_sub:
            if is_dev or has_custom_key:
                # Auto-replenish in development or with custom key so operation doesn't fail
                await sub_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "credits_remaining": 1000,
                            "credits_total": 1000,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
                updated_sub = await sub_collection.find_one_and_update(
                    {
                        "user_id": user_id,
                        "credits_remaining": {"$gte": cost},
                    },
                    {
                        "$inc": {"credits_remaining": -cost},
                        "$set": {"updated_at": datetime.now(timezone.utc)},
                    },
                    return_document=ReturnDocument.AFTER,
                )

            if not updated_sub:
                current = await sub_collection.find_one({"user_id": user_id})
                remaining = current.get("credits_remaining", 0) if current else 0
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"INSUFFICIENT_CREDITS: Required {cost}, Remaining {remaining}",
                )
            
        # Record transaction
        tx_collection = db["credit_transactions"]
        tx = {
            "user_id": user_id,
            "transaction_type": "deduction",
            "amount": cost,
            "feature": action,
            "balance_before": updated_sub["credits_remaining"] + cost,
            "balance_after": updated_sub["credits_remaining"],
            "created_at": datetime.now(timezone.utc)
        }
        await tx_collection.insert_one(tx)
        
        if updated_sub is not None:
            updated_sub["success"] = True
        return updated_sub

    @staticmethod
    async def refund_credits(db, user_id: str, action: str, job_id: str = None) -> dict:
        """Refunds credits (e.g. if an async job fails right away). Idempotent if job_id provided."""
        cost = FEATURE_PRICING.get(action, 1)
        
        if cost == 0:
            return {"success": True}
            
        tx_collection = db["credit_transactions"]
        
        # Ensure idempotency
        if job_id:
            existing_refund = await tx_collection.find_one({
                "user_id": user_id,
                "transaction_type": "refund",
                "reference_id": job_id
            })
            if existing_refund:
                return {"success": True, "message": "Already refunded"}
            
        sub_collection = db["subscriptions"]
        updated_sub = await sub_collection.find_one_and_update(
            {"user_id": user_id},
            {
                "$inc": {"credits_remaining": cost},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            },
            return_document=ReturnDocument.AFTER
        )
        
        if updated_sub:
            tx = {
                "user_id": user_id,
                "transaction_type": "refund",
                "amount": cost,
                "feature": action,
                "balance_before": updated_sub["credits_remaining"] - cost,
                "balance_after": updated_sub["credits_remaining"],
                "created_at": datetime.now(timezone.utc)
            }
            if job_id:
                tx["reference_id"] = job_id
                
            await tx_collection.insert_one(tx)
            
        return updated_sub

    @staticmethod
    async def grant_credits(db, user_id: str, amount: int, reason: str, reference_id: str = None) -> dict:
        """
        Atomically grants credits to a user and logs the transaction.
        Idempotent: If a grant with reference_id already exists, returns existing subscription without re-crediting.
        """
        if amount <= 0:
            return await CreditService.get_or_create_subscription(db, user_id)

        tx_col = db["credit_transactions"]
        if reference_id:
            existing_grant = await tx_col.find_one({
                "user_id": user_id,
                "transaction_type": "grant",
                "reference_id": reference_id
            })
            if existing_grant:
                return await CreditService.get_or_create_subscription(db, user_id)

        # Ensure base subscription exists
        await CreditService.get_or_create_subscription(db, user_id)
        
        now = datetime.now(timezone.utc)
        sub_col = db["subscriptions"]
        
        # Get current balance before
        sub_before = await sub_col.find_one({"user_id": user_id})
        balance_before = sub_before.get("credits_remaining", 0) if sub_before else 0

        updated_sub = await sub_col.find_one_and_update(
            {"user_id": user_id},
            {
                "$inc": {
                    "credits_remaining": amount,
                    "credits_total": amount
                },
                "$set": {"updated_at": now}
            },
            return_document=ReturnDocument.AFTER
        )

        balance_after = updated_sub.get("credits_remaining", balance_before + amount)

        tx = {
            "user_id": user_id,
            "transaction_type": "grant",
            "amount": amount,
            "feature": reason,
            "reference_id": reference_id,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "created_at": now
        }
        await tx_col.insert_one(tx)
        return updated_sub

    @staticmethod
    async def get_credit_summary(db, user_id: str) -> dict:
        """
        Returns credit summary: total granted, total consumed/deducted, and remaining balance.
        """
        sub = await CreditService.get_or_create_subscription(db, user_id)
        remaining = sub.get("credits_remaining", 0)
        total_in_sub = sub.get("credits_total", remaining)

        cursor = db["credit_transactions"].find({"user_id": user_id})
        total_granted = 0
        total_consumed = 0
        async for tx in cursor:
            ttype = tx.get("transaction_type")
            amt = tx.get("amount", 0)
            if ttype == "grant":
                total_granted += amt
            elif ttype == "deduction":
                total_consumed += amt
            elif ttype == "refund":
                total_consumed -= amt

        if total_granted == 0:
            total_granted = total_in_sub

        return {
            "plan_id": sub.get("plan_id", "FREE"),
            "credits_total": max(total_granted, total_in_sub),
            "credits_granted": max(total_granted, total_in_sub),
            "credits_consumed": max(total_consumed, 0),
            "credits_remaining": remaining
        }

    @staticmethod
    async def get_history(db, user_id: str):
        cursor = db["credit_transactions"].find({"user_id": user_id}).sort("created_at", -1)
        history = []
        async for tx in cursor:
            tx["id"] = str(tx.pop("_id"))
            history.append(tx)
        return history
