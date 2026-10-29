import json
import uuid
import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import HTTPException
from pymongo.collection import ReturnDocument
from bson import ObjectId
from app.core.config import settings
from app.core.billing_config import PLANS
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

class PayinService:
    @staticmethod
    async def create_payment(
        db,
        user_id: str,
        user_email: str,
        plan_id: str,
        billing_cycle: str = "monthly",
        user_name: Optional[str] = None,
        user_mobile: Optional[str] = None
    ) -> Dict[str, Any]:
        normalized_plan_id = (plan_id or "").upper().strip()
        if normalized_plan_id not in PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        plan = PLANS[normalized_plan_id]
        if plan["price"] == 0:
            raise HTTPException(status_code=400, detail="Cannot create payment for FREE plan")
            
        cycle = (billing_cycle or "monthly").lower().strip()
        if cycle not in ["monthly", "quarterly", "yearly"]:
            raise HTTPException(status_code=400, detail="Invalid billing cycle. Must be monthly, quarterly, or yearly")

        cycle_pricing = plan.get("billing_cycles", {}).get(cycle)
        if cycle_pricing and "price" in cycle_pricing:
            base_amount = float(cycle_pricing["price"])
        else:
            base_amount = float(plan.get("base_price", plan["price"]))
            
        if not settings.PAYIN_URL or not settings.PAYIN_TOKEN:
            raise HTTPException(status_code=500, detail="Finunique Payin configuration missing")

        order_id = f"ORDER_{uuid.uuid4().hex[:12].upper()}"
        if normalized_plan_id == "HIRE_INFLUENCER":
            gst_rate = 0.0
            gst_amount = 0.0
            total_amount = base_amount
        elif plan.get("gst_applicable"):
            gst_rate = float(plan.get("gst_rate", 0.18))
            gst_amount = float(round(base_amount * gst_rate, 2))
            total_amount = float(round(base_amount + gst_amount, 2))
        else:
            gst_rate = 0.0
            gst_amount = 0.0
            total_amount = base_amount
        
        # Clean & sanitize email (Finunique strictly requires a valid email string)
        clean_email = (user_email or "").strip()
        if not clean_email or "@" not in clean_email:
            phone_clean = (user_mobile or "").replace("+", "").strip() if user_mobile else ""
            if phone_clean:
                clean_email = f"user_{phone_clean}@dhandagrow.com"
            else:
                clean_email = f"user_{user_id}@dhandagrow.com"

        now = datetime.now(timezone.utc)
        cycle_multiplier = 3 if cycle == "quarterly" else (12 if cycle == "yearly" else 1)
        credits_to_grant = plan.get("credits", 0) * cycle_multiplier

        transaction = {
            "user_id": user_id,
            "plan_id": normalized_plan_id,
            "plan_name": plan["name"],
            "base_amount": base_amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "billing_cycle": cycle,
            "amount": total_amount,
            "currency": plan.get("currency", "INR"),
            "order_id": order_id,
            "status": "pending",
            "purchased_credits": credits_to_grant,
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        callback_url = getattr(settings, "PAYIN_CALLBACK_URL", None) or f"{(settings.BACKEND_URL or 'https://api.dhandagrow.com').rstrip('/')}/api/v1/payments/payin/callback"
        frontend_url = (settings.FRONTEND_URL or "https://dhandagrow.com").rstrip("/")
        redirect_url = f"{frontend_url}/subscription?order_id={order_id}"

        payload = {
            "amount": total_amount,
            "email": clean_email,
            "reference": order_id,
            "userId": user_id,
            "callback_url": callback_url,
            "callbackUrl": callback_url,
            "redirect_url": redirect_url,
            "redirectURL": redirect_url,
        }
        if user_name:
            payload["name"] = user_name
        if user_mobile:
            mobile_digits = "".join(c for c in str(user_mobile) if c.isdigit())
            if len(mobile_digits) >= 10:
                payload["mobile"] = mobile_digits[-10:]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.PAYIN_URL,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code >= 400:
                    err_text = response.text
                    logger.error(f"Payin API error HTTP {response.status_code}: {err_text}")
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id},
                        {"$set": {
                            "status": "failed",
                            "failure_reason": f"Payin API error {response.status_code}: {err_text[:200]}",
                            "updated_at": datetime.now(timezone.utc)
                        }}
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=f"Payment Gateway API failed (HTTP {response.status_code}). Please retry."
                    )

                data = response.json()
                
                payment_url = None
                upi_url = None
                provider_ref = order_id
                qr_code = None
                if data.get("data") and isinstance(data["data"], dict):
                    d_obj = data["data"]
                    redirect_raw = d_obj.get("redirectURL") or ""
                    if str(redirect_raw).startswith("upi://"):
                        upi_url = str(redirect_raw)
                        qr_code = upi_url
                    payment_url = d_obj.get("redirectEx") or d_obj.get("redirectURL")
                    provider_ref = d_obj.get("reference") or d_obj.get("orderId") or d_obj.get("txnId") or order_id
                    qr_code = d_obj.get("qrCode") or d_obj.get("qr") or qr_code
                
                if not payment_url:
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "failed", "failure_reason": "Missing redirectURL in Payin response", "updated_at": datetime.now(timezone.utc)}}
                    )
                    raise HTTPException(status_code=502, detail="Invalid Payment Gateway response")
                
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {
                        "status": "initiated",
                        "payment_url": payment_url,
                        "upi_url": upi_url,
                        "provider_reference": provider_ref,
                        "qr_code": qr_code,
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "payment_url": payment_url,
                    "upi_url": upi_url,
                    "qr_code": qr_code,
                    "provider_reference": provider_ref,
                    "amount": total_amount,
                    "currency": plan.get("currency", "INR"),
                    "plan_name": plan["name"],
                    "status": "pending",
                    "billing_cycle": cycle
                }
        except httpx.RequestError:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": "Payment Gateway timeout", "updated_at": datetime.now(timezone.utc)}}
            )
            raise HTTPException(status_code=504, detail="Payment Gateway timeout")

    @staticmethod
    async def verify_payment_with_provider(db, order_id: str) -> Dict[str, Any]:
        """
        Officially verifies payment status server-side with the Payin provider (Finunique).
        Queries provider status endpoint, processes the verified response,
        activates the subscription if paid, and updates the payment transaction.
        """
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            return {"success": False, "status": "not_found", "message": "Transaction not found"}

        if transaction.get("status") == "success":
            return {
                "success": True,
                "status": "success",
                "order_id": order_id,
                "amount": transaction.get("amount"),
                "plan_id": transaction.get("plan_id"),
                "verified": True,
                "message": "Payment verified and subscription active"
            }

        status_url = getattr(settings, "PAYIN_STATUS_URL", None)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                finunique_get_url = f"{(settings.PAYIN_URL or 'https://server.finuniques.in/api/v1/payment/payin').rstrip('/')}/{order_id}"
                res = await client.get(finunique_get_url, headers=headers)
                if res.status_code != 200 and status_url:
                    res = await client.post(status_url, json={"reference": order_id, "orderId": order_id}, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    status_payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    if not status_payload.get("orderId") and not status_payload.get("reference"):
                        status_payload["orderId"] = order_id
                    callback_res = await PayinService.process_callback(db, status_payload, headers=dict(res.headers))
                    return {
                        "success": callback_res.get("success", False),
                        "status": callback_res.get("status", transaction.get("status")),
                        "order_id": order_id,
                        "verified": (callback_res.get("status") == "success"),
                        "message": callback_res.get("message", "Status checked with provider")
                    }
                else:
                    return {
                        "success": False,
                        "status": transaction.get("status", "pending"),
                        "order_id": order_id,
                        "verified": False,
                        "message": f"Provider check returned HTTP {res.status_code}"
                    }
        except Exception as e:
            return {
                "success": False,
                "status": transaction.get("status", "pending"),
                "order_id": order_id,
                "verified": False,
                "message": f"Network or provider error: {str(e)}"
            }

    @staticmethod
    async def process_callback(db, payload: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
        order_id = (
            payload.get("orderId")
            or payload.get("reference")
            or payload.get("order_id")
            or payload.get("client_txn_id")
            or payload.get("txn_id")
        )
        if not order_id:
            return {"success": False, "status": "failed", "message": "Missing orderId"}
            
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            return {"success": False, "status": "failed", "message": "Unknown order"}
            
        if transaction.get("status") == "success":
            return {"success": True, "status": "success", "message": "Already processed"}
            
        response_code = str(payload.get("responseCode") or payload.get("code") or payload.get("status") or payload.get("txnStatus") or "").strip().upper()
        payload_status = str(payload.get("status") or payload.get("txnStatus") or payload.get("payment_status") or "").strip().upper()
        now = datetime.now(timezone.utc)
        
        is_success = (response_code in ["100", "SUCCESS", "PAID", "COMPLETED", "200"] or payload_status in ["SUCCESS", "PAID", "COMPLETED"])
        
        if is_success:
            payload_amount = float(payload.get("amount") or payload.get("txnAmount") or payload.get("total_amount") or 0)
            transaction_amount = float(transaction["amount"])
            base_amount = float(transaction.get("base_amount") or transaction_amount)
            
            amount_matches = False
            for expected in [transaction_amount, base_amount]:
                if abs(payload_amount - expected) < 0.05 or \
                   abs(payload_amount - expected * 100) < 5.0 or \
                   abs(payload_amount / 100 - expected) < 0.05:
                    amount_matches = True
                    break
                
            if not amount_matches:
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "failed", "failure_reason": f"Amount mismatch: received {payload_amount}, expected {transaction_amount}", "updated_at": now}}
                )
                return {"success": False, "status": "failed", "message": "Amount mismatch"}
                
            external_tx_id = (
                payload.get("pgTransId")
                or payload.get("txnId")
                or payload.get("bank_ref_no")
                or payload.get("provider_reference")
                or order_id
            )
            updated_tx = await db["payment_transactions"].find_one_and_update(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": {
                    "status": "success", 
                    "external_transaction_id": external_tx_id,
                    "verified_at": now,
                    "updated_at": now,
                    "raw_callback": {k: str(v) for k, v in payload.items() if k not in ["secret", "token", "password"]}
                }},
                return_document=ReturnDocument.AFTER
            )
            
            if not updated_tx:
                return {"success": True, "status": "success", "message": "Already processed"}
            
            if transaction["plan_id"] != "HIRE_INFLUENCER":
                cycle = transaction.get("billing_cycle", "monthly")
                await SubscriptionService.upgrade_plan(
                    db, 
                    transaction["user_id"], 
                    transaction["plan_id"],
                    billing_cycle=cycle,
                    reference_id=order_id,
                    transaction_id=order_id,
                    payment_provider="finunique_payin",
                    amount=float(transaction.get("amount", 0))
                )

                # Mark plan activation onboarding completed
                from app.services.plan_onboarding_service import PlanOnboardingService
                await PlanOnboardingService.sync_business_plan_status(
                    db,
                    user_id=transaction["user_id"],
                    plan_id=transaction["plan_id"],
                    billing_cycle=cycle
                )
            return {"success": True, "status": "success", "message": "Payment verified and plan activated"}
            
        elif response_code in ["101", "PENDING", "INITIATED"] or payload_status in ["PENDING", "INITIATED"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": {"status": "pending", "failure_reason": payload.get("responseDescription", "Payment pending"), "updated_at": now}}
            )
            return {"success": False, "status": "pending", "message": "Payment pending"}
            
        elif response_code in ["103", "CANCELLED", "CANCELED"] or payload_status in ["CANCELLED", "CANCELED"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": {"status": "cancelled", "failure_reason": payload.get("responseDescription", "Payment cancelled by user"), "updated_at": now}}
            )
            return {"success": False, "status": "cancelled", "message": "Payment cancelled"}
            
        elif response_code in ["104", "EXPIRED"] or payload_status in ["EXPIRED"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": {"status": "expired", "failure_reason": payload.get("responseDescription", "Payment expired"), "updated_at": now}}
            )
            return {"success": False, "status": "expired", "message": "Payment expired"}
        elif response_code in ["102", "FAILED", "FAILURE", "ERROR"] or payload_status in ["FAILED", "FAILURE", "ERROR"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": {"status": "failed", "failure_reason": payload.get("responseDescription", "Payment failed"), "updated_at": now}}
            )
            return {"success": False, "status": "failed", "message": "Payment failed"}
        else:
            current_status = transaction.get("status", "pending")
            return {"success": False, "status": current_status, "message": payload.get("responseDescription", "Payment pending or status inconclusive")}

    @staticmethod
    async def cancel_payment(
        db,
        user_id: str,
        order_id: str,
        reason: Optional[str] = "User cancelled payment"
    ) -> Dict[str, Any]:
        """
        Safely cancels a pending or initiated payment order for the user.
        - Checks that the order belongs to the user.
        - If already successful, refuses cancellation (preserves confirmed payments).
        - Queries the payment provider to ensure payment didn't succeed right before cancellation.
        - If confirmed cancelled/pending with provider, marks the order cancelled in the database.
        """
        transaction = await db["payment_transactions"].find_one({"order_id": order_id, "user_id": user_id})
        if not transaction:
            raise HTTPException(status_code=404, detail="Order not found")

        # 1. If already completed/success, never cancel
        if transaction.get("status") == "success":
            return {
                "success": False,
                "status": "success",
                "order_id": order_id,
                "can_cancel": False,
                "current_status": "success",
                "message": "Payment has already been successfully verified and completed. Cancellation not allowed."
            }

        # 2. If already cancelled, return idempotent success
        if transaction.get("status") == "cancelled":
            return {
                "success": True,
                "status": "cancelled",
                "order_id": order_id,
                "can_cancel": True,
                "current_status": "cancelled",
                "message": "Payment order is already cancelled."
            }

        # 3. Verify server-side with provider to make sure the user did not just pay at the gateway
        try:
            provider_check = await PayinService.verify_payment_with_provider(db, order_id)
            if provider_check.get("verified") or provider_check.get("status") == "success":
                return {
                    "success": False,
                    "status": "success",
                    "order_id": order_id,
                    "can_cancel": False,
                    "current_status": "success",
                    "message": "Payment was already completed with the provider. Plan activated."
                }
        except Exception as e:
            logger.warning(f"Error checking provider status before cancellation of {order_id}: {e}")

        # 4. Notify provider of cancellation if supported
        try:
            cancel_url = getattr(settings, "PAYIN_CANCEL_URL", None) or f"{(settings.PAYIN_URL or '').rstrip('/')}/cancel"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(cancel_url, json={"orderId": order_id, "reference": order_id}, headers=headers)
        except Exception:
            pass

        # 5. Atomically update transaction status to cancelled if not success
        now = datetime.now(timezone.utc)
        result = await db["payment_transactions"].find_one_and_update(
            {"order_id": order_id, "status": {"$ne": "success"}},
            {"$set": {
                "status": "cancelled",
                "cancelled_at": now,
                "failure_reason": reason or "Cancelled by user",
                "updated_at": now
            }},
            return_document=ReturnDocument.AFTER
        )

        if not result or result.get("status") != "cancelled":
            return {
                "success": False,
                "status": "success",
                "order_id": order_id,
                "can_cancel": False,
                "current_status": "success",
                "message": "Payment succeeded concurrently and could not be cancelled."
            }

        return {
            "success": True,
            "status": "cancelled",
            "order_id": order_id,
            "can_cancel": True,
            "current_status": "cancelled",
            "message": "Payment order cancelled successfully."
        }

    @staticmethod
    async def get_user_transactions(
        db,
        user_id: str,
        page: int = 1,
        limit: int = 10,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieves paginated, user-scoped transaction history sorted by creation date descending.
        Preserves all historical attempts (success, initiated, pending, failed, cancelled).
        """
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if status:
            clean_status = status.strip().lower()
            query["status"] = clean_status

        total = await db["payment_transactions"].count_documents(query)
        safe_page = max(1, page)
        safe_limit = min(max(1, limit), 100)
        skip = (safe_page - 1) * safe_limit

        cursor = db["payment_transactions"].find(query).sort("created_at", -1).skip(skip).limit(safe_limit)

        items = []
        async for doc in cursor:
            p_id = doc.get("plan_id", "UNKNOWN")
            p_config = PLANS.get(p_id, {})
            p_credits = doc.get("purchased_credits")
            if p_credits is None:
                cycle = doc.get("billing_cycle", "monthly")
                mult = 3 if cycle == "quarterly" else (12 if cycle == "yearly" else 1)
                p_credits = p_config.get("credits", 0) * mult

            created = doc.get("created_at")
            verified = doc.get("verified_at")
            cancelled = doc.get("cancelled_at")
            completed = verified or cancelled or (doc.get("updated_at") if doc.get("status") in ["success", "failed", "cancelled", "expired"] else None)

            provider_ref = doc.get("provider_reference") or doc.get("external_transaction_id") or doc.get("order_id")

            items.append({
                "id": str(doc["_id"]),
                "order_id": doc.get("order_id", ""),
                "provider_reference": provider_ref,
                "external_transaction_id": doc.get("external_transaction_id"),
                "plan_id": p_id,
                "plan_name": doc.get("plan_name") or p_config.get("name", p_id),
                "amount": float(doc.get("amount", 0.0)),
                "base_amount": doc.get("base_amount"),
                "gst_amount": doc.get("gst_amount"),
                "currency": doc.get("currency", "INR"),
                "billing_cycle": doc.get("billing_cycle", "monthly"),
                "status": doc.get("status", "pending"),
                "failure_reason": doc.get("failure_reason"),
                "payment_url": doc.get("payment_url"),
                "purchased_credits": p_credits,
                "created_at": created,
                "completed_at": completed,
                "verified_at": verified,
                "cancelled_at": cancelled
            })

        total_pages = max(1, (total + safe_limit - 1) // safe_limit)
        return {
            "success": True,
            "total": total,
            "page": safe_page,
            "limit": safe_limit,
            "total_pages": total_pages,
            "data": items
        }

    @staticmethod
    async def reset_test_subscription(
        db,
        user_id: str,
        admin_override: bool = False
    ) -> Dict[str, Any]:
        """
        Safely resets a test user's ₹1 TEST_PLAN subscription and entitlements,
        enabling the payment flow to be repeated from clean state.
        Guarantees:
        - Refuses to reset active production paid plans unless admin_override is explicitly True.
        - Preserves genuine paid transaction audit history (never erases or falsifies records).
        - Cancels any dangling pending/initiated test orders.
        - Balances credit ledger and resets subscription back to FREE plan.
        - Clears plan onboarding completion flag so user can re-trigger plan selection and checkout.
        """
        sub = await db["subscriptions"].find_one({"user_id": str(user_id)})
        current_plan = (sub.get("plan_id") or "FREE").upper().strip() if sub else "FREE"

        # Safe guard: Only TEST_PLAN or FREE or test plans can be reset without admin override
        if current_plan not in ["TEST_PLAN", "TEST", "FREE"] and not admin_override:
            raise HTTPException(
                status_code=400,
                detail=f"Safety restriction: Cannot reset plan '{current_plan}'. Reset is only permitted for TEST_PLAN subscriptions."
            )

        now = datetime.now(timezone.utc)
        uid = str(user_id)

        # 1. Preserve successful paid transactions audit trail
        # Cancel any dangling pending or initiated test transactions
        cancelled_orders = []
        dangling_cursor = db["payment_transactions"].find({
            "user_id": uid,
            "status": {"$in": ["pending", "initiated"]}
        })
        async for dangling in dangling_cursor:
            oid = dangling.get("order_id")
            await db["payment_transactions"].update_one(
                {"order_id": oid},
                {"$set": {
                    "status": "cancelled",
                    "failure_reason": "Reset test order before completion",
                    "cancelled_at": now,
                    "updated_at": now
                }}
            )
            cancelled_orders.append(oid)

        # Collect preserved success order ids for audit report
        audit_preserved = []
        paid_cursor = db["payment_transactions"].find({"user_id": uid, "status": "success"})
        async for paid in paid_cursor:
            audit_preserved.append(paid.get("order_id"))

        # 2. Reset Subscription to FREE with standard 5 credits
        credits_before = sub.get("credits_remaining", 0) if sub else 0
        target_credits = 5

        await db["subscriptions"].update_one(
            {"user_id": uid},
            {
                "$set": {
                    "plan_id": "FREE",
                    "plan": "FREE",
                    "billing_cycle": "monthly",
                    "status": "active",
                    "features": PLANS["FREE"]["features"],
                    "verified_payment": False,
                    "credits_remaining": target_credits,
                    "credits_total": target_credits,
                    "test_plan_reset_at": now,
                    "updated_at": now
                },
                "$unset": {
                    "activated_at": "",
                    "expires_at": ""
                }
            },
            upsert=True
        )

        # 3. Log credit ledger adjustment to maintain audit integrity
        credit_adjustment = target_credits - credits_before
        if credit_adjustment != 0:
            await db["credit_transactions"].insert_one({
                "user_id": uid,
                "transaction_type": "adjustment",
                "amount": credit_adjustment,
                "feature": "test_plan_reset",
                "reference_id": f"reset_test_{uid}_{now.strftime('%Y%m%d%H%M%S')}",
                "balance_before": credits_before,
                "balance_after": target_credits,
                "created_at": now
            })

        # 4. Revert Business Document plan onboarding state
        await db["businesses"].update_one(
            {"$or": [{"owner_id": uid}, {"ownerId": uid}, {"user_id": uid}]},
            {"$set": {
                "active_plan_id": "FREE",
                "plan_activation_completed": False,
                "plan_selection_skipped": False,
                "updated_at": now
            }}
        )

        # 5. Revert User Document onboarding completed flag so user can re-trigger
        if ObjectId.is_valid(uid):
            await db["users"].update_one(
                {"_id": ObjectId(uid)},
                {"$set": {
                    "onboardingCompleted": False,
                    "updated_at": now
                }}
            )

        return {
            "success": True,
            "message": "Test plan subscription reset successfully. You can now repeat the payment flow.",
            "user_id": uid,
            "previous_plan": current_plan,
            "current_plan": "FREE",
            "new_plan": "FREE",
            "credits_remaining": target_credits,
            "credits_available": target_credits,
            "audit_preserved_transactions": audit_preserved,
            "preserved_paid_orders": audit_preserved,
            "cancelled_pending_orders": cancelled_orders
        }
