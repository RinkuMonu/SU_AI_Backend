import hmac
import hashlib
import base64
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.core.billing_config import PLANS, calculate_plan_gst
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService

logger = logging.getLogger(__name__)

class CashfreeService:
    @classmethod
    def get_base_url(cls) -> str:
        if (settings.CASHFREE_ENV or "TEST").upper() == "PROD":
            return "https://api.cashfree.com/pg"
        return "https://sandbox.cashfree.com/pg"

    @classmethod
    def get_headers(cls) -> Dict[str, str]:
        return {
            "x-client-id": settings.CASHFREE_APP_ID,
            "x-client-secret": settings.CASHFREE_SECRET_KEY,
            "x-api-version": settings.CASHFREE_API_VERSION or "2023-08-01",
            "Content-Type": "application/json"
        }

    @classmethod
    async def ensure_cashfree_plan(cls, plan_id: str, cycle: str, plan_data: dict, recurring_amount: float) -> str:
        """
        Creates or retrieves the Cashfree recurring plan corresponding to local plan + billing cycle.
        """
        cf_plan_id = f"{plan_id.upper()}_{cycle.upper()}"
        base_url = cls.get_base_url()
        headers = cls.get_headers()

        # Map interval and type
        if cycle == "monthly":
            interval_type = "MONTH"
            intervals = 1
            max_cycles = 60  # up to 5 years
        elif cycle == "quarterly":
            interval_type = "MONTH"
            intervals = 3
            max_cycles = 20
        elif cycle == "yearly":
            interval_type = "YEAR"
            intervals = 1
            max_cycles = 5
        else:
            interval_type = "MONTH"
            intervals = 1
            max_cycles = 12

        clean_name = f"{plan_data.get('name', plan_id)} {cycle.capitalize()}".replace("(", "").replace(")", "").strip()[:50]
        plan_payload = {
            "plan_id": cf_plan_id,
            "plan_name": clean_name,
            "plan_type": "PERIODIC",
            "plan_currency": plan_data.get("currency", "INR"),
            "plan_recurring_amount": float(recurring_amount),
            "plan_max_amount": float(max(recurring_amount * 2, 5000.0)),  # Mandate upper limit
            "plan_max_cycles": max_cycles,
            "plan_intervals": intervals,
            "plan_interval_type": interval_type
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Check if plan exists
            get_res = await client.get(f"{base_url}/plans/{cf_plan_id}", headers=headers)
            if get_res.status_code == 200:
                p_data = get_res.json() if get_res.headers.get("content-type", "").startswith("application/json") else {}
                existing_amt = float(p_data.get("plan_recurring_amount") or 0)
                if abs(existing_amt - float(recurring_amount)) < 0.05:
                    return cf_plan_id
                # Existing plan amount mismatch (e.g. was 799.0 without GST), create versioned plan ID
                cf_plan_id = f"{cf_plan_id}_{int(recurring_amount)}"
                plan_payload["plan_id"] = cf_plan_id
                get_res2 = await client.get(f"{base_url}/plans/{cf_plan_id}", headers=headers)
                if get_res2.status_code == 200:
                    return cf_plan_id

            # Create plan
            create_res = await client.post(f"{base_url}/plans", json=plan_payload, headers=headers)
            if create_res.status_code in [200, 201]:
                return cf_plan_id
            
            # If already exists error
            err_data = create_res.json() if create_res.headers.get("content-type", "").startswith("application/json") else {}
            if create_res.status_code == 400 and "already exists" in str(err_data).lower():
                return cf_plan_id

            logger.error("Failed to create Cashfree plan %s: %s %s", cf_plan_id, create_res.status_code, create_res.text)
            raise HTTPException(status_code=502, detail=f"Failed to register billing plan with Cashfree: {create_res.text}")

    @classmethod
    async def create_subscription(
        cls,
        db,
        user_id: str,
        user_email: str,
        user_name: Optional[str],
        user_phone: Optional[str],
        plan_id: str,
        billing_cycle: str = "monthly",
        return_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates Cashfree recurring subscription mandate with ₹1 initial auth amount.
        """
        normalized_plan = (plan_id or "").upper().strip()
        if normalized_plan not in PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan selected")

        plan = PLANS[normalized_plan]
        if plan.get("price", 0) == 0:
            raise HTTPException(status_code=400, detail="Cannot create subscription for FREE plan")

        cycle = (billing_cycle or "monthly").lower().strip()
        if cycle not in ["monthly", "quarterly", "yearly"]:
            raise HTTPException(status_code=400, detail="Invalid billing cycle. Must be monthly, quarterly, or yearly")

        # Determine pricing
        cycle_pricing = plan.get("billing_cycles", {}).get(cycle)
        if cycle_pricing and "price" in cycle_pricing:
            base_amount = float(cycle_pricing["price"])
        else:
            base_amount = float(plan.get("base_price", plan["price"]))

        # Decimal-safe 18% GST calculation
        gst_info = calculate_plan_gst(base_amount)
        gst_rate = gst_info["gst_rate"]
        gst_percentage = gst_info["gst_percentage"]
        gst_amount = gst_info["gst_amount"]
        recurring_total = gst_info["total_payable"]

        # Cashfree credentials verification
        if not settings.CASHFREE_APP_ID or not settings.CASHFREE_SECRET_KEY:
            raise HTTPException(status_code=500, detail="Cashfree payment gateway configuration missing")

        # 1. Ensure recurring plan exists on Cashfree
        cf_plan_id = await cls.ensure_cashfree_plan(normalized_plan, cycle, plan, recurring_total)

        # 2. Generate unique subscription reference
        subscription_id = f"SUB_{uuid.uuid4().hex[:12].upper()}"

        # Clean customer phone (Cashfree requires valid phone, fallback to default 10-digit if absent)
        phone = "".join(filter(str.isdigit, str(user_phone or "")))
        if len(phone) < 10:
            phone = "9999999999"
        else:
            phone = phone[-10:]

        customer_details = {
            "customer_id": f"CUST_{user_id[:20]}",
            "customer_name": user_name or "Subscriber",
            "customer_email": user_email or "user@example.com",
            "customer_phone": phone
        }

        default_return_url = return_url or f"{settings.FRONTEND_URL}/payment/success?order_id={subscription_id}&sub_id={subscription_id}"

        sub_payload = {
            "subscription_id": subscription_id,
            "plan_details": {
                "plan_id": cf_plan_id
            },
            "customer_details": customer_details,
            "authorization_details": {
                "authorization_amount": recurring_total
            },
            "subscription_meta": {
                "return_url": default_return_url,
                "notification_channel": ["EMAIL", "SMS"]
            }
        }

        base_url = cls.get_base_url()
        headers = cls.get_headers()

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(f"{base_url}/subscriptions", json=sub_payload, headers=headers)
            
            if res.status_code not in [200, 201]:
                logger.error("Cashfree subscription create error: %s %s", res.status_code, res.text)
                raise HTTPException(status_code=502, detail=f"Cashfree subscription initiation failed: {res.text}")

            cf_data = res.json()

        # Payment/Session URL for frontend checkout SDK or redirect
        session_id = cf_data.get("subscription_session_id")
        cf_sub_id = cf_data.get("cf_subscription_id")
        
        # Resolve Cashfree Hosted Subscriptions Checkout Page
        payment_url = None
        if session_id:
            try:
                subs_checkout_base = "https://api.cashfree.com" if (settings.CASHFREE_ENV or "TEST").upper() == "PROD" else "https://sandbox.cashfree.com"
                async with httpx.AsyncClient(timeout=10.0) as cf_client:
                    chk_res = await cf_client.post(
                        f"{subs_checkout_base}/pg/view/sessions/checkout/subs",
                        data={
                            "subs_session_id": session_id,
                            "x_request_id": "x_request_id_form_subs_atom",
                            "form_id": "form_subs_id_atom",
                            "browser_meta": "e30=",
                            "platform": "c"
                        },
                        follow_redirects=False
                    )
                    payment_url = chk_res.headers.get("location")
            except Exception as e:
                logger.warning("Could not resolve Cashfree hosted subs URL: %s", e)
                payment_url = None

        now = datetime.now(timezone.utc)
        record = {
            "user_id": user_id,
            "customer_email": user_email,
            "subscription_id": subscription_id,
            "cf_subscription_id": cf_sub_id,
            "subscription_session_id": session_id,
            "payment_url": payment_url,
            "plan_id": normalized_plan,
            "plan_name": plan.get("name"),
            "billing_cycle": cycle,
            "auth_amount": recurring_total,
            "recurring_amount": recurring_total,
            "base_amount": base_amount,
            "gst_amount": gst_amount,
            "gst_rate": gst_rate,
            "currency": plan.get("currency", "INR"),
            "status": "INITIALIZED",
            "created_at": now,
            "updated_at": now,
            "raw_init_response": cf_data
        }

        await db["payment_subscriptions"].insert_one(record)

        # Record initial pending transaction for user billing history
        from app.services.payin_service import PayinService
        try:
            tx_seq_id = await PayinService.generate_transaction_id(db)
        except Exception:
            tx_seq_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

        tx_record = {
            "transaction_id": tx_seq_id,
            "order_id": subscription_id,
            "subscription_id": subscription_id,
            "cf_subscription_id": cf_sub_id,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "user_phone": phone,
            "plan_id": normalized_plan,
            "plan_name": plan.get("name", normalized_plan),
            "billing_cycle": cycle,
            "amount": recurring_total,
            "base_amount": base_amount,
            "gst_amount": gst_amount,
            "gst_rate": gst_rate,
            "currency": "INR",
            "payment_mode": "AutoPay Mandate",
            "payment_gateway": "Cashfree Subscriptions & AutoPay",
            "payment_provider": "cashfree",
            "status": "pending",
            "payment_url": payment_url,
            "created_at": now,
            "updated_at": now
        }
        try:
            await db["payment_transactions"].insert_one(tx_record)
        except Exception as tx_err:
            logger.warning("Failed to insert initial payment_transactions record: %s", tx_err)

        return {
            "success": True,
            "subscription_id": subscription_id,
            "order_id": subscription_id,
            "cf_subscription_id": cf_sub_id,
            "subscription_session_id": session_id,
            "payment_url": payment_url,
            "status": "INITIALIZED",
            "auth_amount": recurring_total,
            "recurring_amount": recurring_total,
            "amount": recurring_total,
            "base_amount": base_amount,
            "gst_amount": gst_amount,
            "gst_rate": gst_rate,
            "plan_id": normalized_plan,
            "plan_name": plan.get("name", normalized_plan),
            "billing_cycle": cycle,
            "currency": "INR"
        }

    @classmethod
    def verify_webhook_signature(cls, raw_body: bytes, timestamp: str, signature: str) -> bool:
        """
        Verifies Cashfree webhook signature using HMAC-SHA256.
        """
        if not signature or not timestamp or not settings.CASHFREE_SECRET_KEY:
            return False
        try:
            signature_data = f"{timestamp}".encode("utf-8") + raw_body
            computed = base64.b64encode(
                hmac.new(
                    settings.CASHFREE_SECRET_KEY.encode("utf-8"),
                    signature_data,
                    hashlib.sha256
                ).digest()
            ).decode("utf-8")
            return hmac.compare_digest(computed, signature)
        except Exception as e:
            logger.error("Error verifying Cashfree webhook signature: %s", e)
            return False

    @classmethod
    async def process_webhook(cls, db, payload: Dict[str, Any], raw_body: bytes = b"", headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Handles Cashfree recurring subscription webhook events.
        """
        # Event type
        event_type = payload.get("type") or payload.get("event")
        data = payload.get("data") or {}
        sub_data = data.get("subscription") or data

        sub_id = sub_data.get("subscription_id")
        if not sub_id:
            logger.warning("Cashfree webhook missing subscription_id in payload: %s", payload)
            return {"success": False, "message": "Missing subscription_id"}

        subscription = await db["payment_subscriptions"].find_one({"subscription_id": sub_id})
        if not subscription:
            logger.warning("Subscription %s not found in database", sub_id)
            return {"success": False, "message": "Subscription not found"}

        now = datetime.now(timezone.utc)
        auth_details = sub_data.get("authorization_details") or {}
        sub_status = sub_data.get("subscription_status") or payload.get("status")

        # Activate plan if mandate approved / active
        if event_type in ["SUBSCRIPTION_ACTIVE", "SUBSCRIPTION_NEW", "SUBSCRIPTION_ACTIVATED"] or sub_status == "ACTIVE":
            if subscription.get("status") != "ACTIVE":
                await db["payment_subscriptions"].update_one(
                    {"subscription_id": sub_id},
                    {
                        "$set": {
                            "status": "ACTIVE",
                            "auth_status": auth_details.get("authorization_status", "SUCCESS"),
                            "cf_subscription_id": sub_data.get("cf_subscription_id") or subscription.get("cf_subscription_id"),
                            "activated_at": now,
                            "updated_at": now,
                            "last_webhook_payload": payload
                        }
                    }
                )

                # Grant user subscription & plan credits
                user_id = subscription["user_id"]
                plan_id = subscription["plan_id"]
                cycle = subscription["billing_cycle"]
                
                try:
                    await SubscriptionService.upgrade_plan(db, user_id, plan_id, billing_cycle=cycle)
                    logger.info("Activated subscription for user %s with plan %s", user_id, plan_id)
                except Exception as ex:
                    logger.error("Failed to activate user subscription in SubscriptionService: %s", ex)

                # Update transaction record and dispatch MSG91 invoice email
                try:
                    await db["payment_transactions"].update_one(
                        {"order_id": sub_id},
                        {"$set": {"status": "success", "completed_at": now, "verified_at": now, "updated_at": now}}
                    )
                    from app.services.invoice_service import InvoiceService
                    cf_tx = await db["payment_transactions"].find_one({"order_id": sub_id})
                    if cf_tx and not cf_tx.get("invoice_email_sent"):
                        await InvoiceService.send_invoice_email(db, cf_tx)
                except Exception as e:
                    logger.warning("Failed to update payment_transactions on webhook active: %s", e)

            return {"success": True, "message": "Subscription activated successfully"}

        elif event_type in ["SUBSCRIPTION_FAILED", "SUBSCRIPTION_CANCELLED", "SUBSCRIPTION_TERMINATED"] or sub_status in ["FAILED", "CANCELLED"]:
            await db["payment_subscriptions"].update_one(
                {"subscription_id": sub_id},
                {
                    "$set": {
                        "status": sub_status or "FAILED",
                        "failure_reason": payload.get("message") or "Mandate failed or cancelled",
                        "updated_at": now,
                        "last_webhook_payload": payload
                    }
                }
            )
            return {"success": True, "message": f"Subscription marked as {sub_status}"}

        # Save generic webhook payload
        await db["payment_subscriptions"].update_one(
            {"subscription_id": sub_id},
            {
                "$set": {
                    "last_webhook_payload": payload,
                    "updated_at": now
                }
            }
        )
        return {"success": True, "message": "Webhook recorded"}

    @classmethod
    async def get_subscription_status(cls, db, subscription_id: str, current_user_id: str) -> Dict[str, Any]:
        """
        Fetches subscription status from DB and syncs with Cashfree if needed.
        """
        record = await db["payment_subscriptions"].find_one({"subscription_id": subscription_id})
        if not record:
            raise HTTPException(status_code=404, detail="Subscription not found")

        if record["user_id"] != str(current_user_id):
            raise HTTPException(status_code=403, detail="Not authorized to view this subscription")

        # Sync with Cashfree live API
        base_url = cls.get_base_url()
        headers = cls.get_headers()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{base_url}/subscriptions/{subscription_id}", headers=headers)
                if res.status_code == 200:
                    cf_data = res.json()
                    cf_status = cf_data.get("subscription_status")
                    prev_status = record.get("status")
                    if cf_status:
                        if cf_status != prev_status:
                            await db["payment_subscriptions"].update_one(
                                {"subscription_id": subscription_id},
                                {"$set": {"status": cf_status, "updated_at": datetime.now(timezone.utc)}}
                            )
                            record["status"] = cf_status
                        # Automatically activate plan in subscription collection
                        if cf_status in ["ACTIVE", "AUTHENTICATED", "APPROVAL_PENDING"]:
                            user_sub = await db["subscriptions"].find_one({"user_id": record["user_id"]})
                            current_plan = (user_sub.get("plan") or user_sub.get("plan_id") or "").upper() if user_sub else ""
                            target_plan = (record.get("plan_id") or "").upper()
                            if current_plan != target_plan or not (user_sub and user_sub.get("verified_payment")):
                                await SubscriptionService.upgrade_plan(
                                    db, record["user_id"], record["plan_id"], billing_cycle=record.get("billing_cycle", "monthly")
                                )
                                logger.info("Upgraded user %s to plan %s via Cashfree sync", record["user_id"], record["plan_id"])
        except Exception as e:
            logger.warning("Could not sync live Cashfree subscription status: %s", e)

        is_active = (record.get("status") in ["ACTIVE", "AUTHENTICATED"])
        if is_active:
            try:
                await db["payment_transactions"].update_one(
                    {"order_id": subscription_id},
                    {"$set": {"status": "success", "completed_at": datetime.now(timezone.utc), "verified_at": datetime.now(timezone.utc)}}
                )
                from app.services.invoice_service import InvoiceService
                cf_tx = await db["payment_transactions"].find_one({"order_id": subscription_id})
                if cf_tx and not cf_tx.get("invoice_email_sent"):
                    await InvoiceService.send_invoice_email(db, cf_tx)
            except Exception as e:
                logger.warning("Could not dispatch invoice email during subscription status sync: %s", e)

        return {
            "success": is_active,
            "subscription_id": subscription_id,
            "order_id": subscription_id,
            "cf_subscription_id": record.get("cf_subscription_id"),
            "status": "ACTIVE" if is_active else record.get("status", "INITIALIZED"),
            "auth_amount": record.get("auth_amount", record.get("recurring_amount", 0.0)),
            "recurring_amount": record.get("recurring_amount", 0.0),
            "amount": record.get("recurring_amount", record.get("auth_amount", 0.0)),
            "plan_id": record.get("plan_id"),
            "plan_name": record.get("plan_name"),
            "billing_cycle": record.get("billing_cycle"),
            "customer_email": record.get("customer_email"),
            "auth_status": record.get("auth_status"),
            "verified": is_active,
            "message": "Subscription is active" if is_active else f"Subscription status: {record.get('status', 'INITIALIZED')}"
        }
