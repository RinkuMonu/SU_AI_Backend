from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException, status
from pymongo.collection import ReturnDocument
from app.core.billing_config import FEATURE_PRICING, NON_CREDIT_FEATURES, UNPRICED_FEATURES

class CreditService:
    @staticmethod
    def _get_action_cost(action: str) -> int:
        normalized_action = (action or "").strip().lower().replace("-", "_")
        if normalized_action in NON_CREDIT_FEATURES:
            return 0
        if normalized_action in UNPRICED_FEATURES or normalized_action not in FEATURE_PRICING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"CREDIT_COST_UNCONFIGURED: Credit pricing for '{action}' is not set.",
            )
        return FEATURE_PRICING[normalized_action]

    @staticmethod
    def _uid_query(uid: str):
        s = str(uid or "").strip()
        if ObjectId.is_valid(s):
            return {"$in": [s, ObjectId(s)]}
        return s

    @staticmethod
    async def get_or_create_subscription(db, user_id: str):
        from app.services.subscription_service import SubscriptionService
        return await SubscriptionService.get_or_create_subscription(db, user_id)

    @staticmethod
    async def check_credits(db, user_id: str, action: str):
        """Check if user has enough credits without deducting. Raises 402 if not."""
        cost = CreditService._get_action_cost(action)
        if cost == 0:
            return True
        sub = await CreditService.get_or_create_subscription(db, user_id)
        if sub.get("credits_remaining", 0) < cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"INSUFFICIENT_CREDITS: Required {cost}, Remaining: {sub.get('credits_remaining', 0)}",
            )
        return True

    @staticmethod
    async def deduct_credits(db, user_id: str, action: str) -> dict:
        """Atomically deducts credits for an action and logs the transaction. Raises 402 if insufficient."""
        cost = CreditService._get_action_cost(action)
        if cost == 0:
            return {"success": True}

        # Ensure subscription exists
        await CreditService.get_or_create_subscription(db, user_id)

        # Atomic deduction using $gte to prevent negative balance
        sub_collection = db["subscriptions"]
        updated_sub = await sub_collection.find_one_and_update(
            {
                "user_id": CreditService._uid_query(user_id),
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
            "user_id": CreditService._uid_query(user_id),
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
        cost = CreditService._get_action_cost(action)
        if cost == 0:
            return {"success": True}
            
        tx_collection = db["credit_transactions"]
        
        # Ensure idempotency
        if job_id:
            existing_refund = await tx_collection.find_one({
                "user_id": CreditService._uid_query(user_id),
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
                "user_id": CreditService._uid_query(user_id),
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
                "user_id": CreditService._uid_query(user_id),
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
            "user_id": CreditService._uid_query(user_id),
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
        total_consumed = 0
        async for tx in cursor:
            ttype = tx.get("transaction_type")
            amt = tx.get("amount", 0)
            if ttype == "deduction":
                total_consumed += amt
            elif ttype == "refund":
                total_consumed -= amt

        return {
            "plan_id": sub.get("plan_id", "FREE"),
            "credits_total": total_in_sub,
            "credits_granted": total_in_sub,
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
