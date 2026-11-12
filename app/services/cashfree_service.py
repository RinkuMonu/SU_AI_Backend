import asyncio
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
    def _build_return_url(cls, return_url: Optional[str], subscription_id: str) -> str:
        url = (return_url or "").strip()
        if not url:
            base_frontend = getattr(settings, "CASHFREE_RETURN_URL", None) or getattr(settings, "FRONTEND_URL", "https://dhandagrow.com")
            base_frontend = str(base_frontend or "https://dhandagrow.com").strip().rstrip("/")
            url = f"{base_frontend}/payment/success?order_id={subscription_id}&sub_id={subscription_id}"
        else:
            url = (
                url.replace("{subscription_id}", subscription_id)
                .replace("{order_id}", subscription_id)
            )

        is_prod = (settings.CASHFREE_ENV or "TEST").upper() == "PROD"

        if is_prod:
            # Cashfree Subscriptions and Orders APIs strictly mandate HTTPS for all URLs in production
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            elif not url.startswith("https://"):
                url = f"https://{url.lstrip('/')}"
        else:
            # For Sandbox / TEST local development, keep http:// for localhost so browser doesn't hit ERR_SSL_PROTOCOL_ERROR
            if "localhost" in url.lower() or "127.0.0.1" in url:
                if url.startswith("https://localhost"):
                    url = "http://" + url[len("https://"):]
                elif url.startswith("https://127.0.0.1"):
                    url = "http://" + url[len("https://"):]
                elif not url.startswith("http://"):
                    url = f"http://{url.lstrip('/')}"
            else:
                if url.startswith("http://"):
                    url = "https://" + url[len("http://"):]
                elif not url.startswith("https://"):
                    url = f"https://{url.lstrip('/')}"

        return url

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
        rec_amt_float = float(recurring_amount)

        # NPCI & RBI rules for recurring mandates:
        # UPI AutoPay and Cards Standing Instructions (SI) are strictly limited to ₹15,000 maximum mandate limit.
        # If recurring_amount <= 15,000, we must keep plan_max_amount <= 15,000 so Cashfree enables UPI and Cards!
        if rec_amt_float <= 15000.0:
            plan_max_amount = rec_amt_float
        else:
            plan_max_amount = rec_amt_float

        plan_payload = {
            "plan_id": cf_plan_id,
            "plan_name": clean_name,
            "plan_type": "PERIODIC",
            "plan_currency": plan_data.get("currency", "INR"),
            "plan_recurring_amount": rec_amt_float,
            "plan_max_amount": plan_max_amount,
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
                existing_max = float(p_data.get("plan_max_amount") or 0)

                # Amount matches AND (if amount <= 15k, existing_max must also be <= 15k so UPI & Cards are not hidden)
                is_max_compliant = (rec_amt_float > 15000.0) or (existing_max <= 15000.0)
                if abs(existing_amt - rec_amt_float) < 0.05 and is_max_compliant:
                    return cf_plan_id

                # If existing plan has max_amount > 15000 (which broke UPI/Cards) or amount mismatch, use V2 plan ID
                cf_plan_id = f"{cf_plan_id}_V2"
                plan_payload["plan_id"] = cf_plan_id
                plan_payload["plan_max_amount"] = plan_max_amount
                get_res2 = await client.get(f"{base_url}/plans/{cf_plan_id}", headers=headers)
                if get_res2.status_code == 200:
                    p_data2 = get_res2.json() if get_res2.headers.get("content-type", "").startswith("application/json") else {}
                    existing_max2 = float(p_data2.get("plan_max_amount") or 0)
                    if (rec_amt_float > 15000.0) or (existing_max2 <= 15000.0):
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

        subscription_id = f"SUB_{uuid.uuid4().hex[:12].upper()}"
        default_return_url = cls._build_return_url(return_url, subscription_id)

        # 1. Primary Flow: Cashfree Payment Gateway Orders API
        # Provides complete multi-channel checkout: Credit Cards, Debit Cards, UPI (QR, Apps, ID), Net Banking, and Wallets.
        # This completely resolves the missing card options issue caused by recurring mandate card restrictions.
        payment_url = None
        session_id = None
        cf_sub_id = None
        cf_data = {}
        last_error_detail = None
        gateway_flow = "order"

        if settings.CASHFREE_APP_ID and settings.CASHFREE_SECRET_KEY:
            base_url = cls.get_base_url()
            headers = cls.get_headers()
            is_prod = (settings.CASHFREE_ENV or "TEST").upper() == "PROD"
            cf_flow = getattr(settings, "CASHFREE_FLOW", "ORDER").upper()

            if cf_flow == "SUBSCRIPTION":
                # Optional pure recurring mandate flow if explicitly configured
                try:
                    cf_plan_id = await cls.ensure_cashfree_plan(normalized_plan, cycle, plan, recurring_total)
                except Exception as plan_err:
                    logger.warning("ensure_cashfree_plan notice: %s", plan_err)
                    cf_plan_id = f"{normalized_plan}_{cycle.upper()}"

                sub_payload = {
                    "subscription_id": subscription_id,
                    "plan_details": {
                        "plan_id": cf_plan_id
                    },
                    "customer_details": customer_details,
                    "authorization_details": {
                        "authorization_amount": recurring_total,
                        "payment_methods": ["card", "upi", "enach"] if recurring_total <= 15000.0 else ["enach", "card", "upi"]
                    },
                    "subscription_meta": {
                        "return_url": default_return_url,
                        "notification_channel": ["EMAIL", "SMS"],
                        "payment_methods": "card,upi,enach"
                    }
                }
                try:
                    async with httpx.AsyncClient(timeout=25.0) as client:
                        res = await client.post(f"{base_url}/subscriptions", json=sub_payload, headers=headers)
                        if res.status_code in [200, 201]:
                            cf_data = res.json()
                            session_id = cf_data.get("subscription_session_id")
                            cf_sub_id = cf_data.get("cf_subscription_id")
                            gateway_flow = "subscription"
                            if session_id:
                                payment_url = f"https://payments.cashfree.com/order/#{session_id}" if is_prod else f"https://payments-test.cashfree.com/order/#{session_id}"
                            logger.info("Created Cashfree AutoPay subscription %s (session %s)", subscription_id, session_id)
                        else:
                            last_error_detail = res.text
                except Exception as sub_err:
                    last_error_detail = str(sub_err)

            # Standard & Default Flow: Cashfree PG Orders (Cards + UPI + NetBanking + Wallets enabled)
            if not session_id:
                order_payload = {
                    "order_id": subscription_id,
                    "order_amount": float(recurring_total),
                    "order_currency": plan.get("currency", "INR"),
                    "customer_details": customer_details,
                    "order_meta": {
                        "return_url": default_return_url,
                        "notify_url": getattr(settings, "CASHFREE_WEBHOOK_URL", None) or f"{(settings.BACKEND_URL or 'https://api.dhandagrow.com').rstrip('/')}/api/v1/payments/cashfree/webhook"
                    },
                    "order_note": f"DhandaGrow {plan.get('name', normalized_plan)} Plan ({cycle.capitalize()})"
                }
                try:
                    async with httpx.AsyncClient(timeout=25.0) as client:
                        res = await client.post(f"{base_url}/orders", json=order_payload, headers=headers)
                        if res.status_code in [200, 201]:
                            cf_data = res.json()
                            session_id = cf_data.get("payment_session_id")
                            cf_sub_id = str(cf_data.get("cf_order_id") or "")
                            gateway_flow = "order"
                            if session_id:
                                payment_url = f"https://payments.cashfree.com/order/#{session_id}" if is_prod else f"https://payments-test.cashfree.com/order/#{session_id}"
                            logger.info("Successfully created Cashfree PG Order %s with all payment methods: Cards, UPI, Netbanking (session %s)", subscription_id, session_id)
                        else:
                            logger.error("Cashfree order create returned %s: %s", res.status_code, res.text)
                            try:
                                last_error_detail = res.json().get("message") or res.text
                            except Exception:
                                last_error_detail = res.text
                except Exception as ord_err:
                    logger.error("Cashfree order creation exception: %s", ord_err)
                    last_error_detail = str(ord_err)

        # 2. Resilient Fallback: If Cashfree PG failed or returned no payment_url, try Finunique Payin
        if not payment_url and getattr(settings, "PAYIN_URL", None) and getattr(settings, "PAYIN_TOKEN", None):
            try:
                from app.services.payin_service import PayinService
                payin_res = await PayinService.create_payment(
                    db=db,
                    user_id=user_id,
                    user_email=user_email,
                    plan_id=normalized_plan,
                    billing_cycle=cycle,
                    user_name=user_name,
                    user_mobile=phone,
                    frontend_url=getattr(settings, "FRONTEND_URL", "https://dhandagrow.com")
                )
                if payin_res.get("payment_url"):
                    return {
                        "success": True,
                        "subscription_id": payin_res.get("order_id") or subscription_id,
                        "order_id": payin_res.get("order_id") or subscription_id,
                        "payment_url": payin_res.get("payment_url"),
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
            except Exception as payin_err:
                logger.error("Finunique Payin fallback failed: %s", payin_err)

        if not payment_url:
            detail_msg = last_error_detail or "Payment gateway temporarily unavailable. Please retry shortly."
            raise HTTPException(status_code=502, detail=f"Payment gateway error: {detail_msg}")

        now = datetime.now(timezone.utc)
        record = {
            "user_id": user_id,
            "customer_email": user_email,
            "subscription_id": subscription_id,
            "order_id": subscription_id,
            "cf_subscription_id": cf_sub_id,
            "subscription_session_id": session_id,
            "payment_session_id": session_id,
            "gateway_flow": gateway_flow,
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
            "payment_mode": "Cards / UPI / NetBanking" if gateway_flow == "order" else "AutoPay Mandate",
            "payment_gateway": "Cashfree Payment Gateway" if gateway_flow == "order" else "Cashfree Subscriptions & AutoPay",
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

        # Dispatch MSG91 auto-debit initiated notification email (non-blocking)
        try:
            from app.services.msg91_email_service import Msg91EmailService
            asyncio.create_task(Msg91EmailService.send_auto_debit_initiated_email(db, tx_record))
        except Exception as mail_err:
            logger.warning("Could not queue auto-debit initiated email: %s", mail_err)

        return {
            "success": True,
            "subscription_id": subscription_id,
            "order_id": subscription_id,
            "cf_subscription_id": cf_sub_id,
            "subscription_session_id": session_id,
            "payment_session_id": session_id,
            "environment": "production" if (settings.CASHFREE_ENV or "TEST").upper() == "PROD" else "sandbox",
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
        Handles Cashfree webhook events for both Orders (Payment Gateway) and Subscriptions (AutoPay).
        """
        # Event type
        event_type = (payload.get("type") or payload.get("event") or "").upper()
        data = payload.get("data") or {}
        sub_data = data.get("subscription_details") or data.get("subscription") or {}
        order_data = data.get("order") or {}
        payment_data = data.get("payment") or {}

        # Extract order / subscription ID flexibly from any Cashfree event schema
        sub_id = (
            sub_data.get("subscription_id")
            or order_data.get("order_id")
            or payload.get("order_id")
            or data.get("order_id")
            or payload.get("subscription_id")
        )
        if not sub_id:
            logger.warning("Cashfree webhook missing subscription_id / order_id in payload: %s", payload)
            return {"success": False, "message": "Missing subscription_id / order_id"}

        subscription = await db["payment_subscriptions"].find_one({
            "$or": [{"subscription_id": sub_id}, {"order_id": sub_id}]
        })
        if not subscription:
            logger.warning("Subscription / Order %s not found in database", sub_id)
            return {"success": False, "message": "Subscription / Order not found"}

        now = datetime.now(timezone.utc)
        auth_details = sub_data.get("authorization_details") or data.get("authorization_details") or {}
        sub_status = (
            sub_data.get("subscription_status")
            or sub_data.get("status")
            or payload.get("status")
            or ""
        ).upper()
        payment_status = (payment_data.get("payment_status") or "").upper()

        is_success = (
            event_type in ["PAYMENT_SUCCESS_WEBHOOK", "SUBSCRIPTION_ACTIVE", "SUBSCRIPTION_ACTIVATED", "ORDER_PAID"]
            or payment_status == "SUCCESS"
            or sub_status in ["ACTIVE", "AUTHENTICATED", "PAID", "SUCCESS"]
        )

        # Activate plan if payment confirmed
        if is_success:
            await SubscriptionService.upgrade_plan(
                db,
                subscription["user_id"],
                subscription["plan_id"],
                billing_cycle=subscription.get("billing_cycle", "monthly"),
                reference_id=sub_id,
                transaction_id=sub_id,
                amount=subscription.get("auth_amount") or subscription.get("recurring_amount"),
                payment_provider="cashfree",
            )
            await db["payment_subscriptions"].update_one(
                {"$or": [{"subscription_id": sub_id}, {"order_id": sub_id}]},
                {
                    "$set": {
                        "status": "ACTIVE",
                        "auth_status": auth_details.get("authorization_status", "SUCCESS"),
                        "cf_subscription_id": sub_data.get("cf_subscription_id") or str(payment_data.get("cf_payment_id") or subscription.get("cf_subscription_id") or ""),
                        "activated_at": subscription.get("activated_at") or now,
                        "updated_at": now,
                        "last_webhook_payload": payload,
                    }
                },
            )
            pay_group = payment_data.get("payment_group")
            pay_mode = pay_group.replace("_", " ").title() if pay_group else "Cards / UPI / NetBanking"
            prov_ref = payment_data.get("bank_reference") or str(payment_data.get("cf_payment_id") or "")
            await db["payment_transactions"].update_one(
                {"$or": [{"order_id": sub_id}, {"subscription_id": sub_id}]},
                {"$set": {
                    "status": "success",
                    "payment_mode": pay_mode,
                    "provider_reference": prov_ref,
                    "completed_at": now,
                    "verified_at": now,
                    "updated_at": now
                }}
            )
            cf_tx = await db["payment_transactions"].find_one({"$or": [{"order_id": sub_id}, {"subscription_id": sub_id}]})
            if cf_tx and not cf_tx.get("invoice_email_sent"):
                from app.services.invoice_service import InvoiceService
                await InvoiceService.send_invoice_email(db, cf_tx)
            logger.info("Activated subscription/order for user %s with plan %s via webhook", subscription["user_id"], subscription["plan_id"])
            return {"success": True, "message": "Subscription / Order activated successfully"}

        elif (
            event_type in ["PAYMENT_FAILED_WEBHOOK", "SUBSCRIPTION_FAILED", "SUBSCRIPTION_CANCELLED", "SUBSCRIPTION_TERMINATED"]
            or payment_status in ["FAILED", "USER_DROPPED", "CANCELLED"]
            or sub_status in ["FAILED", "CANCELLED", "TERMINATED", "REJECTED", "EXPIRED"]
        ):
            fail_reason = (
                payment_data.get("payment_message")
                or payload.get("message")
                or "Payment authorization failed or cancelled"
            )
            await db["payment_subscriptions"].update_one(
                {"$or": [{"subscription_id": sub_id}, {"order_id": sub_id}]},
                {
                    "$set": {
                        "status": sub_status or payment_status or "FAILED",
                        "failure_reason": fail_reason,
                        "updated_at": now,
                        "last_webhook_payload": payload
                    }
                }
            )
            # Update payment_transactions and dispatch MSG91 payment failed email
            try:
                await db["payment_transactions"].update_one(
                    {"$or": [{"order_id": sub_id}, {"subscription_id": sub_id}], "status": {"$ne": "success"}},
                    {
                        "$set": {
                            "status": "failed",
                            "failure_reason": fail_reason,
                            "updated_at": now
                        }
                    }
                )
                from app.services.invoice_service import InvoiceService
                cf_tx = await db["payment_transactions"].find_one({"$or": [{"order_id": sub_id}, {"subscription_id": sub_id}]})
                if cf_tx and not cf_tx.get("payment_failed_email_sent"):
                    await InvoiceService.send_payment_failed_email(db, cf_tx, failure_reason=fail_reason)
            except Exception as mail_ex:
                logger.warning("Failed to dispatch payment failed email for Cashfree subscription %s: %s", sub_id, mail_ex)

            return {"success": True, "message": f"Order / Subscription marked as failed"}

        # Save generic webhook payload
        await db["payment_subscriptions"].update_one(
            {"$or": [{"subscription_id": sub_id}, {"order_id": sub_id}]},
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
        record = await db["payment_subscriptions"].find_one({
            "$or": [{"subscription_id": subscription_id}, {"order_id": subscription_id}]
        })
        if not record:
            tx_fallback = await db["payment_transactions"].find_one({
                "$or": [{"order_id": subscription_id}, {"subscription_id": subscription_id}]
            })
            if not tx_fallback:
                raise HTTPException(status_code=404, detail="Subscription or Order not found")
            if tx_fallback["user_id"] != str(current_user_id):
                raise HTTPException(status_code=403, detail="Not authorized to view this transaction")
            record = {
                "user_id": tx_fallback["user_id"],
                "subscription_id": subscription_id,
                "order_id": subscription_id,
                "plan_id": tx_fallback.get("plan_id"),
                "plan_name": tx_fallback.get("plan_name"),
                "billing_cycle": tx_fallback.get("billing_cycle", "monthly"),
                "auth_amount": tx_fallback.get("amount", 0.0),
                "recurring_amount": tx_fallback.get("amount", 0.0),
                "base_amount": tx_fallback.get("base_amount"),
                "gst_amount": tx_fallback.get("gst_amount"),
                "gst_rate": tx_fallback.get("gst_rate"),
                "status": tx_fallback.get("status", "pending").upper(),
                "customer_email": tx_fallback.get("user_email")
            }

        if record["user_id"] != str(current_user_id):
            raise HTTPException(status_code=403, detail="Not authorized to view this subscription")

        # Sync with Cashfree live API
        base_url = cls.get_base_url()
        headers = cls.get_headers()
        cf_payment_details = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                cf_status = None
                
                # Check Orders API first (Cashfree PG orders)
                res = await client.get(f"{base_url}/orders/{subscription_id}", headers=headers)
                if res.status_code == 200:
                    cf_data = res.json()
                    order_status = (cf_data.get("order_status") or "").upper()
                    if order_status == "PAID":
                        cf_status = "ACTIVE"
                    elif order_status in ["EXPIRED", "TERMINATED", "FAILED"]:
                        cf_status = "FAILED"
                    else:
                        cf_status = order_status

                    if cf_status == "ACTIVE":
                        try:
                            pay_res = await client.get(f"{base_url}/orders/{subscription_id}/payments", headers=headers)
                            if pay_res.status_code == 200:
                                payments_list = pay_res.json()
                                if isinstance(payments_list, list) and payments_list:
                                    cf_payment_details = next(
                                        (p for p in payments_list if (p.get("payment_status") or "").upper() == "SUCCESS"),
                                        payments_list[0]
                                    )
                        except Exception as pay_err:
                            logger.warning("Could not fetch detailed payments for order %s: %s", subscription_id, pay_err)

                # Fallback to Subscriptions API (recurring mandates)
                if not cf_status:
                    res2 = await client.get(f"{base_url}/subscriptions/{subscription_id}", headers=headers)
                    if res2.status_code == 200:
                        cf_data2 = res2.json()
                        cf_data2 = cf_data2.get("subscription_details") or cf_data2
                        cf_status = (cf_data2.get("subscription_status") or cf_data2.get("status") or "").upper()

                prev_status = record.get("status")
                if cf_status:
                    if cf_status != prev_status:
                        await db["payment_subscriptions"].update_one(
                            {"$or": [{"subscription_id": subscription_id}, {"order_id": subscription_id}]},
                            {"$set": {"status": cf_status, "updated_at": datetime.now(timezone.utc)}}
                        )
                        record["status"] = cf_status
                    # Automatically activate plan in subscription collection
                    if cf_status in ["ACTIVE", "AUTHENTICATED", "PAID", "SUCCESS"]:
                        await SubscriptionService.upgrade_plan(
                            db,
                            record["user_id"],
                            record["plan_id"],
                            billing_cycle=record.get("billing_cycle", "monthly"),
                            reference_id=subscription_id,
                            transaction_id=subscription_id,
                            amount=record.get("auth_amount") or record.get("recurring_amount"),
                            payment_provider="cashfree",
                        )
                        logger.info("Upgraded user %s to plan %s via Cashfree sync", record["user_id"], record["plan_id"])
        except Exception as e:
            logger.warning("Could not sync live Cashfree subscription status: %s", e)

        is_active = (record.get("status") in ["ACTIVE", "AUTHENTICATED", "PAID", "SUCCESS"])
        now = datetime.now(timezone.utc)
        if is_active:
            try:
                update_fields = {
                    "status": "success",
                    "completed_at": now,
                    "verified_at": now,
                    "updated_at": now
                }
                if cf_payment_details:
                    pay_group = cf_payment_details.get("payment_group")
                    if pay_group:
                        update_fields["payment_mode"] = pay_group.replace("_", " ").title()
                    bank_ref = cf_payment_details.get("bank_reference") or str(cf_payment_details.get("cf_payment_id") or "")
                    if bank_ref:
                        update_fields["provider_reference"] = bank_ref
                    update_fields["raw_payment_details"] = cf_payment_details

                await db["payment_transactions"].update_one(
                    {"$or": [{"order_id": subscription_id}, {"subscription_id": subscription_id}]},
                    {"$set": update_fields}
                )
                cf_tx = await db["payment_transactions"].find_one({"$or": [{"order_id": subscription_id}, {"subscription_id": subscription_id}]})
                if cf_tx and not cf_tx.get("invoice_email_sent"):
                    from app.services.invoice_service import InvoiceService
                    await InvoiceService.send_invoice_email(db, cf_tx)
            except Exception as e:
                logger.warning("Could not dispatch invoice email during subscription status sync: %s", e)
        elif record.get("status") in ["FAILED", "CANCELLED", "TERMINATED", "REJECTED", "EXPIRED"]:
            try:
                fail_reason = record.get("failure_reason") or f"Payment {record.get('status', 'FAILED').lower()}"
                await db["payment_transactions"].update_one(
                    {"$or": [{"order_id": subscription_id}, {"subscription_id": subscription_id}], "status": {"$ne": "success"}},
                    {"$set": {"status": "failed", "failure_reason": fail_reason, "updated_at": now}}
                )
                from app.services.invoice_service import InvoiceService
                cf_tx = await db["payment_transactions"].find_one({"$or": [{"order_id": subscription_id}, {"subscription_id": subscription_id}]})
                if cf_tx and not cf_tx.get("payment_failed_email_sent"):
                    await InvoiceService.send_payment_failed_email(db, cf_tx, failure_reason=fail_reason)
            except Exception as e:
                logger.warning("Could not dispatch payment failed email during subscription status sync: %s", e)

        return {
            "success": is_active,
            "subscription_id": subscription_id,
            "order_id": subscription_id,
            "cf_subscription_id": record.get("cf_subscription_id"),
            "status": "ACTIVE" if is_active else record.get("status", "INITIALIZED"),
            "auth_amount": record.get("auth_amount", record.get("recurring_amount", 0.0)),
            "recurring_amount": record.get("recurring_amount", 0.0),
            "amount": record.get("recurring_amount", record.get("auth_amount", 0.0)),
            "base_amount": record.get("base_amount"),
            "gst_rate": record.get("gst_rate"),
            "gst_percentage": record.get("gst_percentage"),
            "gst_amount": record.get("gst_amount"),
            "total_payable": record.get("total_payable") or record.get("recurring_amount"),
            "plan_id": record.get("plan_id"),
            "plan_name": record.get("plan_name"),
            "billing_cycle": record.get("billing_cycle"),
            "customer_email": record.get("customer_email"),
            "auth_status": record.get("auth_status"),
            "verified": is_active,
            "message": "Subscription is active" if is_active else f"Subscription status: {record.get('status', 'INITIALIZED')}"
        }
