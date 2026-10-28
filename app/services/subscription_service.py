from datetime import datetime, timezone
from fastapi import HTTPException, status
from pymongo.collection import ReturnDocument
from app.core.billing_config import PLANS

QUALIFYING_PAID_PLANS = {"STARTER", "GROWTH", "PRO", "BUSINESS", "INFLUENCER"}

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
            "billing_cycle": "monthly",
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
        plan_id = (sub.get("plan_id") or "FREE").upper().strip()
        plan_config = PLANS.get(plan_id, PLANS["FREE"])
        now = datetime.now(timezone.utc)

        # 1. Check expiration if set
        expires_at = sub.get("expires_at")
        if expires_at:
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at)
                except Exception:
                    expires_at = None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at and expires_at < now:
                await db["subscriptions"].update_one(
                    {"user_id": user_id},
                    {"$set": {"status": "expired", "updated_at": now}}
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="SUBSCRIPTION_EXPIRED: Your subscription has expired. Please renew to continue using paid features."
                )

        # 2. Check active subscription status
        if sub.get("status") != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SUBSCRIPTION_INACTIVE: Your subscription is not active. Please activate or renew your plan."
            )

        # 3. Check if feature is included in the plan
        features = plan_config.get("features", [])
        if feature_name not in features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"FEATURE_NOT_AVAILABLE: '{feature_name}' is not available on the {plan_id} plan. Please upgrade to access this feature."
            )

        # 4. If this is a paid plan (not FREE), verify that payment is confirmed
        if plan_id != "FREE":
            has_paid_tx = await db["payment_transactions"].find_one({
                "user_id": user_id,
                "status": "success"
            })
            has_paid_history = await db["subscription_history"].find_one({
                "user_id": user_id,
                "payment_status": "paid"
            })
            if not has_paid_tx and not has_paid_history and not sub.get("verified_payment"):
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"PAYMENT_REQUIRED: Access to '{feature_name}' requires an active subscription with verified payment confirmation."
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
    async def upgrade_plan(
        db,
        user_id: str,
        new_plan_id: str,
        billing_cycle: str = "monthly",
        reference_id: str = None,
        transaction_id: str = None,
        payment_provider: str = None,
        amount: float = None
    ):
        normalized_plan_id = (new_plan_id or "").upper().strip()
        if normalized_plan_id not in PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan")
            
        plan_config = PLANS[normalized_plan_id]
        collection = db["subscriptions"]

        # Ensure base subscription record exists
        await SubscriptionService.get_or_create_subscription(db, user_id)
        
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cycle = (billing_cycle or "monthly").lower().strip()
        if cycle == "quarterly":
            days = 90
            multiplier = 3
        elif cycle == "yearly":
            days = 365
            multiplier = 12
        else:
            days = 30
            multiplier = 1
            cycle = "monthly"

        expires_at = now + timedelta(days=days)
        credits_to_add = plan_config.get("credits", 0) * multiplier

        # Update subscription status and validity (without double-incrementing credits)
        updated = await collection.find_one_and_update(
            {"user_id": user_id},
            {
                "$set": {
                    "plan_id": normalized_plan_id,
                    "plan": normalized_plan_id,
                    "billing_cycle": cycle,
                    "status": "active",
                    "features": plan_config.get("features", []),
                    "verified_payment": True,
                    "activated_at": now,
                    "expires_at": expires_at,
                    "updated_at": now
                }
            },
            return_document=ReturnDocument.AFTER
        )

        # Log to credit transactions and increment credits atomically and idempotently
        from app.services.credit_service import CreditService
        credit_ref = reference_id or f"upgrade_{normalized_plan_id}_{user_id}_{now.strftime('%Y%m%d%H%M%S')}"
        if credits_to_add > 0:
            updated = await CreditService.grant_credits(
                db, user_id, credits_to_add,
                reason=f"plan_upgrade_{normalized_plan_id.lower()}",
                reference_id=credit_ref
            )

        # Mark onboarding step 3 completed in businesses
        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "plan_activation_completed": True,
                "plan_activation_completed_at": now,
                "active_plan_id": normalized_plan_id,
                "billing_cycle": cycle,
                "updated_at": now
            }},
            upsert=True
        )

        # Record in subscription_history for billing reports
        if amount is None:
            cycle_pricing = plan_config.get("billing_cycles", {}).get(cycle)
            if cycle_pricing and "price" in cycle_pricing:
                amount = float(cycle_pricing["price"])
            else:
                amount = float(plan_config.get("price", 0))

        await SubscriptionService.record_subscription_history(
            db=db,
            user_id=user_id,
            plan_id=normalized_plan_id,
            plan_name=plan_config.get("name", normalized_plan_id),
            amount=amount,
            currency=plan_config.get("currency", "INR"),
            billing_cycle=cycle,
            payment_status="paid" if amount > 0 else "free_activation",
            payment_provider=payment_provider,
            transaction_id=transaction_id or reference_id,
            credits_granted=credits_to_add,
            valid_until=expires_at
        )

        return updated


    @staticmethod
    async def activate_free_plan(db, user_id: str) -> dict:
        """
        Activates the Free (₹0) plan and records it in subscription and billing history.
        Idempotent: Prevents duplicate history or credit grants on repeat activations.
        """
        now = datetime.now(timezone.utc)
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        
        # Check if already activated in subscription history
        history_col = db["subscription_history"]
        existing_free = await history_col.find_one({"user_id": user_id, "plan_id": "FREE"})
        
        if not existing_free:
            free_record = {
                "user_id": user_id,
                "plan_id": "FREE",
                "plan_name": "Free",
                "amount": 0,
                "currency": "INR",
                "billing_cycle": "monthly",
                "status": "active",
                "payment_status": "free_activation",
                "payment_provider": None,
                "transaction_id": None,
                "credits_granted": 5,
                "invoice_reference": f"INV-FREE-{user_id[:8].upper()}",
                "is_free": True,
                "activated_at": now,
                "valid_until": None,
                "created_at": now
            }
            await history_col.insert_one(free_record)
            
            # Grant free tier credits idempotently
            from app.services.credit_service import CreditService
            await CreditService.grant_credits(
                db, user_id, 5,
                reason="free_plan_activation",
                reference_id=f"free_plan_{user_id}"
            )

        # Mark business record as completed
        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "plan_activation_completed": True,
                "plan_activation_completed_at": now,
                "active_plan_id": "FREE",
                "billing_cycle": "monthly",
                "updated_at": now
            }},
            upsert=True
        )

        # Return updated subscription
        updated = await db["subscriptions"].find_one({"user_id": user_id})
        if updated and "_id" in updated:
            updated["id"] = str(updated.pop("_id"))
        return updated

    @staticmethod
    async def record_subscription_history(
        db,
        user_id: str,
        plan_id: str,
        plan_name: str,
        amount: float,
        currency: str = "INR",
        billing_cycle: str = "monthly",
        payment_status: str = "paid",
        payment_provider: str = None,
        transaction_id: str = None,
        credits_granted: int = 0,
        valid_until: datetime = None
    ) -> dict:
        """
        Records a plan activation or purchase event into subscription_history.
        Idempotent by transaction_id for paid transactions.
        """
        now = datetime.now(timezone.utc)
        history_col = db["subscription_history"]

        if transaction_id:
            existing = await history_col.find_one({"user_id": user_id, "transaction_id": transaction_id})
            if existing:
                return existing

        is_free = (amount == 0 or plan_id.upper() == "FREE")
        inv_ref = f"INV-FREE-{user_id[:8].upper()}" if is_free else f"INV-{transaction_id or now.strftime('%Y%m%d%H%M%S')}"

        record = {
            "user_id": user_id,
            "plan_id": plan_id.upper().strip(),
            "plan_name": plan_name,
            "amount": amount,
            "currency": currency,
            "billing_cycle": billing_cycle,
            "status": "active",
            "payment_status": payment_status,
            "payment_provider": payment_provider,
            "transaction_id": transaction_id,
            "credits_granted": credits_granted,
            "invoice_reference": inv_ref,
            "is_free": is_free,
            "activated_at": now,
            "valid_until": valid_until,
            "created_at": now
        }
        await history_col.insert_one(record)
        return record

    @staticmethod
    async def get_subscription_history(db, user_id: str) -> list:
        """
        Returns all subscription history records (Free and Paid) for the authenticated user.
        """
        cursor = db["subscription_history"].find({"user_id": user_id}).sort("created_at", -1)
        history = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            history.append(doc)
        return history

    @staticmethod
    async def get_billing_report(db, user_id: str) -> dict:
        """
        Comprehensive billing report for the authenticated user:
        - Current active subscription
        - Complete subscription history (free and paid activations)
        - Payment transactions
        - AI credit usage summary and audit history
        """
        # 1. Current subscription
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        if "_id" in sub:
            sub["id"] = str(sub.pop("_id"))
            
        # Ensure free activation is recorded if user is on Free plan and has no history
        history_count = await db["subscription_history"].count_documents({"user_id": user_id})
        if history_count == 0 and sub.get("plan_id") == "FREE":
            await SubscriptionService.activate_free_plan(db, user_id)

        # 2. Subscription history
        sub_history = await SubscriptionService.get_subscription_history(db, user_id)

        # 3. Payment transactions
        tx_cursor = db["payment_transactions"].find({"user_id": user_id}).sort("created_at", -1)
        transactions = []
        async for tx in tx_cursor:
            tx["id"] = str(tx.pop("_id"))
            transactions.append(tx)

        # 4. Credit summary and recent ledger
        from app.services.credit_service import CreditService
        credit_summary = await CreditService.get_credit_summary(db, user_id)
        credit_history = await CreditService.get_history(db, user_id)

        return {
            "user_id": user_id,
            "current_subscription": sub,
            "subscription_history": sub_history,
            "payment_transactions": transactions,
            "credit_summary": credit_summary,
            "credit_transactions": credit_history
        }
