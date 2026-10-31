import re
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
from app.core.billing_config import PLANS, calculate_plan_gst
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

class PayinService:
    @staticmethod
    async def generate_transaction_id(db) -> str:
        """
        Dynamically generates a sequential, unique transaction ID in the format GROWG001, GROWG002, etc.
        Uses an atomic MongoDB find_one_and_update operation on the 'counters' collection.
        Ensures thread-safe and cluster-safe sequential generation.
        """
        counter = await db["counters"].find_one_and_update(
            {"_id": "subscription_transaction_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        seq_num = counter.get("seq", 1)
        return f"GROWG{seq_num:03d}"

    @staticmethod
    def extract_payment_mode(payload: Dict[str, Any]) -> str:
        """
        Extracts and normalizes the payment mode from gateway response/callback payload.
        Returns 'Unknown' if the gateway does not report it or cannot be determined.
        """
        if not payload or not isinstance(payload, dict):
            return "Unknown"

        raw_mode = (
            payload.get("paymentMode")
            or payload.get("payMode")
            or payload.get("mode")
            or payload.get("channel")
            or payload.get("payment_mode")
            or payload.get("method")
            or payload.get("instrument")
            or payload.get("txn_mode")
            or ""
        )
        mode_str = str(raw_mode).strip().upper()
        if not mode_str:
            # Check vpa / upi hints
            if payload.get("vpa") or payload.get("upi_id") or payload.get("upi"):
                return "UPI"
            if payload.get("card_number") or payload.get("card_type"):
                c_type = str(payload.get("card_type", "")).upper()
                return "Credit Card" if "CREDIT" in c_type else "Debit Card"
            return "Unknown"

        if "UPI" in mode_str:
            if "QR" in mode_str:
                return "QR Code"
            return "UPI"
        if "QR" in mode_str:
            return "QR Code"
        if any(nb in mode_str for nb in ["NB", "NETBANKING", "NET_BANKING", "NET BANKING"]):
            return "Net Banking"
        if any(cc in mode_str for cc in ["CC", "CREDIT_CARD", "CREDIT CARD", "CREDIT"]):
            return "Credit Card"
        if any(dc in mode_str for dc in ["DC", "DEBIT_CARD", "DEBIT CARD", "DEBIT"]):
            return "Debit Card"
        if "WALLET" in mode_str:
            return "Wallet"
        if "EMI" in mode_str:
            return "EMI"
        return raw_mode.title() if raw_mode else "Unknown"
    @staticmethod
    async def create_payment(
        db,
        user_id: str,
        user_email: str,
        plan_id: str,
        billing_cycle: str = "monthly",
        user_name: Optional[str] = None,
        user_mobile: Optional[str] = None,
        frontend_url: Optional[str] = None
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
            
        if not getattr(settings, "PAYIN_URL", "") or not getattr(settings, "PAYIN_TOKEN", ""):
            raise HTTPException(status_code=500, detail="Finunique Payin configuration missing")

        order_id = f"ORDER_{uuid.uuid4().hex[:12].upper()}"
        # Decimal-safe 18% GST calculation (Formula: gst_amount = base_price * 0.18, total_amount = base_price + gst_amount)
        gst_info = calculate_plan_gst(base_amount)
        gst_rate = gst_info["gst_rate"]
        gst_percentage = gst_info["gst_percentage"]
        gst_amount = gst_info["gst_amount"]
        total_amount = gst_info["total_payable"]
        
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

        # Lookup user info if not fully provided
        if not user_name or not user_mobile:
            try:
                if ObjectId.is_valid(user_id):
                    u_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
                    if u_doc:
                        user_name = user_name or u_doc.get("name") or u_doc.get("full_name") or u_doc.get("business_name")
                        user_mobile = user_mobile or u_doc.get("phone_number") or u_doc.get("mobile")
            except Exception:
                pass

        # Dynamically generate sequential, unique transaction ID (GROWG001, GROWG002, ...)
        transaction_id = await PayinService.generate_transaction_id(db)

        transaction = {
            "transaction_id": transaction_id,
            "order_id": order_id,
            "user_id": user_id,
            "user_name": user_name,
            "user_email": clean_email,
            "user_phone": user_mobile,
            "plan_id": normalized_plan_id,
            "plan_name": plan["name"],
            "plan_duration": cycle,
            "billing_cycle": cycle,
            "amount": total_amount,
            "base_amount": base_amount,
            "gst_rate": gst_rate,
            "gst_percentage": gst_percentage,
            "gst_amount": gst_amount,
            "total_payable": total_amount,
            "currency": plan.get("currency", "INR"),
            "payment_mode": "Unknown",
            "payment_gateway": "Finunique Payin",
            "payment_provider": "Finunique",
            "gateway_transaction_id": None,
            "status": "pending",
            "purchased_credits": credits_to_grant,
            "credits_included": credits_to_grant,
            "failure_reason": None,
            "refund_details": None,
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        callback_url = getattr(settings, "PAYIN_CALLBACK_URL", None) or f"{(settings.BACKEND_URL or 'https://api.dhandagrow.com').rstrip('/')}/api/v1/payments/payin/callback"
        base_frontend = (frontend_url or settings.FRONTEND_URL or "https://dhandagrow.com").rstrip("/")
        redirect_url = f"{base_frontend}/subscription?order_id={order_id}&tab=transactions"

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
            "Authorization": f"Bearer {getattr(settings, 'PAYIN_TOKEN', '')}"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    getattr(settings, "PAYIN_URL", ""),
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
                
                initial_mode = "QR Code" if (upi_url or qr_code) else "Unknown"
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {
                        "status": "initiated",
                        "payment_url": payment_url,
                        "upi_url": upi_url,
                        "provider_reference": provider_ref,
                        "qr_code": qr_code,
                        "payment_mode": initial_mode,
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                
                return {
                    "success": True,
                    "transaction_id": transaction_id,
                    "order_id": order_id,
                    "payment_url": payment_url,
                    "upi_url": upi_url,
                    "qr_code": qr_code,
                    "provider_reference": provider_ref,
                    "amount": total_amount,
                    "currency": plan.get("currency", "INR"),
                    "plan_name": plan["name"],
                    "status": "pending",
                    "billing_cycle": cycle,
                    "payment_mode": initial_mode
                }
        except httpx.RequestError:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": "Payment Gateway timeout", "updated_at": datetime.now(timezone.utc)}}
            )
            raise HTTPException(status_code=504, detail="Payment Gateway timeout")

    @staticmethod
    async def query_provider_order_status(order_id: str) -> Dict[str, Any]:
        """
        Directly queries Finunique's official server-side API to retrieve official transaction status.
        Uses GET https://server.finuniques.in/api/v1/payment/payin/{order_id} with authorized PAYIN_TOKEN.
        """
        if not getattr(settings, "PAYIN_URL", "") or not getattr(settings, "PAYIN_TOKEN", ""):
            return {"confirmed_success": False, "provider_status": "unconfigured", "data": None}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {getattr(settings, 'PAYIN_TOKEN', '')}"
        }
        status_url = getattr(settings, "PAYIN_STATUS_URL", None)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                finunique_get_url = f"{getattr(settings, 'PAYIN_URL', '').rstrip('/')}/{order_id}"
                res = await client.get(finunique_get_url, headers=headers)
                if res.status_code != 200 and status_url:
                    res = await client.post(status_url, json={"reference": order_id, "orderId": order_id}, headers=headers)

                if res.status_code == 200:
                    data = res.json()
                    status_payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    raw_status = str(status_payload.get("status") or status_payload.get("responseCode") or status_payload.get("code") or "").strip().upper()
                    is_paid = raw_status in ["SUCCESS", "PAID", "COMPLETED", "100", "200"]
                    return {
                        "confirmed_success": is_paid,
                        "provider_status": raw_status,
                        "data": status_payload,
                        "remark": status_payload.get("remark") or status_payload.get("responseDescription") or status_payload.get("message")
                    }
                else:
                    return {
                        "confirmed_success": False,
                        "provider_status": f"HTTP_{res.status_code}",
                        "data": None,
                        "remark": f"Provider returned HTTP {res.status_code}"
                    }
        except Exception as e:
            logger.error(f"Error querying provider status for {order_id}: {e}")
            return {
                "confirmed_success": False,
                "provider_status": "error",
                "data": None,
                "remark": str(e)
            }

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
            "Authorization": f"Bearer {getattr(settings, 'PAYIN_TOKEN', '')}"
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                finunique_get_url = f"{(getattr(settings, 'PAYIN_URL', '') or 'https://server.finuniques.in/api/v1/payment/payin').rstrip('/')}/{order_id}"
                res = await client.get(finunique_get_url, headers=headers)
                if res.status_code != 200 and status_url:
                    res = await client.post(status_url, json={"reference": order_id, "orderId": order_id}, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    status_payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    if not status_payload.get("orderId") and not status_payload.get("reference"):
                        status_payload["orderId"] = order_id
                    callback_res = await PayinService.process_callback(
                        db, status_payload, headers=dict(res.headers), from_provider_verification=True
                    )
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
    async def process_callback(
        db, 
        payload: Dict[str, Any], 
        headers: Dict[str, str] = None,
        from_provider_verification: bool = False
    ) -> Dict[str, Any]:
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
        remark_text = payload.get("remark") or payload.get("responseDescription") or payload.get("message")
        now = datetime.now(timezone.utc)
        
        is_success = (response_code in ["100", "SUCCESS", "PAID", "COMPLETED", "200"] or payload_status in ["SUCCESS", "PAID", "COMPLETED"])
        
        if is_success:
            payload_amount = float(payload.get("amount") or payload.get("txnAmount") or payload.get("total_amount") or 0)
            transaction_amount = float(transaction["amount"])
            base_amount = float(transaction.get("base_amount") or transaction_amount)
            
            # 1. Match amount (handling rupee vs paise representation)
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
                    {"$set": {
                        "status": "failed",
                        "failure_reason": f"Amount mismatch: received {payload_amount}, expected {transaction_amount}",
                        "completed_at": now,
                        "updated_at": now
                    }}
                )
                return {"success": False, "status": "failed", "message": "Amount mismatch"}

            # 2. Match currency if provided
            payload_currency = payload.get("currency") or payload.get("cu")
            if payload_currency and str(payload_currency).strip().upper() != str(transaction.get("currency", "INR")).strip().upper():
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {
                        "status": "failed",
                        "failure_reason": f"Currency mismatch: received {payload_currency}, expected {transaction.get('currency', 'INR')}",
                        "completed_at": now,
                        "updated_at": now
                    }}
                )
                return {"success": False, "status": "failed", "message": "Currency mismatch"}

            # 3. Match intended user if provided
            payload_user_id = payload.get("userId") or payload.get("user_id")
            if payload_user_id and str(payload_user_id).strip() != str(transaction.get("user_id")).strip():
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {
                        "status": "failed",
                        "failure_reason": "User mismatch",
                        "completed_at": now,
                        "updated_at": now
                    }}
                )
                return {"success": False, "status": "failed", "message": "User mismatch"}

            # 4. Match intended plan if provided
            payload_plan_id = payload.get("plan_id") or payload.get("plan")
            if payload_plan_id:
                norm_p = str(payload_plan_id).strip().upper()
                tx_p = str(transaction.get("plan_id", "")).strip().upper()
                plan_ok = (
                    norm_p == tx_p or
                    (norm_p in ["PRO", "GROWTH"] and tx_p in ["PRO", "GROWTH"]) or
                    (norm_p in ["TEST", "TEST_PLAN"] and tx_p in ["TEST", "TEST_PLAN"]) or
                    (norm_p in ["BASIC", "STARTER"] and tx_p in ["BASIC", "STARTER"])
                )
                if not plan_ok:
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id},
                        {"$set": {
                            "status": "failed",
                            "failure_reason": f"Plan mismatch: received {norm_p}, expected {tx_p}",
                            "completed_at": now,
                            "updated_at": now
                        }}
                    )
                    return {"success": False, "status": "failed", "message": "Plan mismatch"}

            # 5. Direct server-side verification check with payment provider if received externally
            is_live_provider = (
                bool(getattr(settings, "PAYIN_URL", "")) and
                "mock" not in str(getattr(settings, "PAYIN_URL", "")).lower() and
                bool(getattr(settings, "PAYIN_TOKEN", "")) and
                "mock" not in str(getattr(settings, "PAYIN_TOKEN", "")).lower()
            )
            if not from_provider_verification and is_live_provider:
                provider_check = await PayinService.query_provider_order_status(order_id)
                if not provider_check.get("confirmed_success"):
                    remark = provider_check.get("remark") or f"Provider reported {provider_check.get('provider_status')}"
                    logger.warning(f"Rejecting unconfirmed callback for order {order_id}: {remark}")
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id, "status": {"$ne": "success"}},
                        {"$set": {
                            "status": "failed",
                            "failure_reason": f"Payment unconfirmed by provider: {remark}",
                            "completed_at": now,
                            "updated_at": now
                        }}
                    )
                    return {"success": False, "status": "failed", "message": f"Payment not confirmed by payment gateway: {remark}"}
                
            external_tx_id = (
                payload.get("pgTransId")
                or payload.get("txnId")
                or payload.get("bank_ref_no")
                or payload.get("bankRefNo")
                or payload.get("utr")
                or payload.get("rrn")
                or payload.get("provider_reference")
                or payload.get("reference")
                or order_id
            )
            verified_payment_mode = PayinService.extract_payment_mode(payload)
            success_update = {
                "status": "success", 
                "external_transaction_id": external_tx_id,
                "gateway_transaction_id": external_tx_id,
                "verified_at": now,
                "completed_at": now,
                "updated_at": now,
                "raw_callback": {k: str(v) for k, v in payload.items() if k not in ["secret", "token", "password"]}
            }
            if verified_payment_mode != "Unknown":
                success_update["payment_mode"] = verified_payment_mode

            updated_tx = await db["payment_transactions"].find_one_and_update(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": success_update, "$unset": {"failure_reason": ""}},
                return_document=ReturnDocument.AFTER
            )
            
            if not updated_tx:
                return {"success": True, "status": "success", "message": "Already processed"}
            
            if transaction["plan_id"] != "HIRE_INFLUENCER":
                cycle = transaction.get("billing_cycle", "monthly")
                pub_tx_id = transaction.get("transaction_id") or order_id
                await SubscriptionService.upgrade_plan(
                    db, 
                    transaction["user_id"], 
                    transaction["plan_id"],
                    billing_cycle=cycle,
                    reference_id=order_id,
                    transaction_id=pub_tx_id,
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

            # Automatically generate invoice and send MSG91 invoice email for verified payment
            try:
                from app.services.invoice_service import InvoiceService
                await InvoiceService.send_invoice_email(db, updated_tx)
            except Exception as mail_ex:
                logger.error("Error in automated invoice email dispatch for %s: %s", order_id, mail_ex)

            return {"success": True, "status": "success", "message": "Payment verified and plan activated"}
            
        elif response_code in ["101", "PENDING", "INITIATED"] or payload_status in ["PENDING", "INITIATED"]:
            p_update = {
                "status": "pending",
                "failure_reason": remark_text or "Payment pending",
                "updated_at": now
            }
            cb_mode = PayinService.extract_payment_mode(payload)
            if cb_mode != "Unknown":
                p_update["payment_mode"] = cb_mode
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": p_update}
            )
            return {"success": False, "status": "pending", "message": "Payment pending"}
            
        elif response_code in ["103", "CANCELLED", "CANCELED"] or payload_status in ["CANCELLED", "CANCELED"]:
            c_update = {
                "status": "cancelled",
                "cancelled_at": now,
                "completed_at": now,
                "failure_reason": remark_text or "Payment cancelled by user",
                "updated_at": now
            }
            cb_mode = PayinService.extract_payment_mode(payload)
            if cb_mode != "Unknown":
                c_update["payment_mode"] = cb_mode
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": c_update}
            )
            # Dispatch payment cancelled email
            try:
                from app.services.invoice_service import InvoiceService
                fail_tx = await db["payment_transactions"].find_one({"order_id": order_id})
                if fail_tx and not fail_tx.get("payment_failed_email_sent"):
                    await InvoiceService.send_payment_failed_email(db, fail_tx, failure_reason=remark_text or "Payment cancelled by user")
            except Exception as mail_ex:
                logger.warning("Error in payment cancelled email dispatch for %s: %s", order_id, mail_ex)

            return {"success": False, "status": "cancelled", "message": "Payment cancelled"}
            
        elif response_code in ["104", "EXPIRED"] or payload_status in ["EXPIRED"]:
            e_update = {
                "status": "expired",
                "completed_at": now,
                "failure_reason": remark_text or "Payment expired",
                "updated_at": now
            }
            cb_mode = PayinService.extract_payment_mode(payload)
            if cb_mode != "Unknown":
                e_update["payment_mode"] = cb_mode
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": e_update}
            )
            return {"success": False, "status": "expired", "message": "Payment expired"}
        elif response_code in ["102", "FAILED", "FAILURE", "ERROR"] or payload_status in ["FAILED", "FAILURE", "ERROR"] or (response_code.isdigit() and int(response_code) >= 400):
            fail_msg = remark_text or "Payment failed or declined by provider"
            f_update = {
                "status": "failed",
                "completed_at": now,
                "failure_reason": fail_msg,
                "updated_at": now
            }
            cb_mode = PayinService.extract_payment_mode(payload)
            if cb_mode != "Unknown":
                f_update["payment_mode"] = cb_mode
            await db["payment_transactions"].update_one(
                {"order_id": order_id, "status": {"$ne": "success"}},
                {"$set": f_update}
            )
            # Dispatch payment failed email
            try:
                from app.services.invoice_service import InvoiceService
                fail_tx = await db["payment_transactions"].find_one({"order_id": order_id})
                if fail_tx and not fail_tx.get("payment_failed_email_sent"):
                    await InvoiceService.send_payment_failed_email(db, fail_tx, failure_reason=fail_msg)
            except Exception as mail_ex:
                logger.warning("Error in payment failed email dispatch for %s: %s", order_id, mail_ex)

            return {"success": False, "status": "failed", "message": "Payment failed"}
        else:
            current_status = transaction.get("status", "pending")
            return {"success": False, "status": current_status, "message": remark_text or "Payment pending or status inconclusive"}

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
            cancel_url = getattr(settings, "PAYIN_CANCEL_URL", None) or f"{(getattr(settings, 'PAYIN_URL', '') or '').rstrip('/')}/cancel"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {getattr(settings, 'PAYIN_TOKEN', '')}"
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

        # Dispatch payment cancelled email
        try:
            from app.services.invoice_service import InvoiceService
            if result and not result.get("payment_failed_email_sent"):
                await InvoiceService.send_payment_failed_email(db, result, failure_reason=reason or "Payment order cancelled by user")
        except Exception as mail_ex:
            logger.warning("Error in cancel payment email dispatch for %s: %s", order_id, mail_ex)

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
        status: Optional[str] = None,
        payment_mode: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[Any] = None,
        date_to: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves paginated, user-scoped transaction history sorted by creation date descending.
        Supports status, payment_mode, search, and date range filters.
        Preserves all historical attempts (success, initiated, pending, failed, cancelled, refunded).
        """
        query: Dict[str, Any] = {"user_id": str(user_id)}

        # Status filter
        if status:
            clean_status = status.strip().lower()
            if clean_status != "all":
                if clean_status in ["pending", "initiated"]:
                    query["status"] = {"$in": ["pending", "initiated"]}
                else:
                    query["status"] = clean_status

        # Payment mode filter
        if payment_mode:
            clean_mode = payment_mode.strip()
            if clean_mode.upper() != "ALL":
                query["payment_mode"] = {"$regex": f"^{re.escape(clean_mode)}$", "$options": "i"}

        # Search filter across transaction ID, order ID, plan name, and gateway references
        if search:
            search_str = search.strip()
            if search_str:
                regex_q = {"$regex": re.escape(search_str), "$options": "i"}
                query["$or"] = [
                    {"transaction_id": regex_q},
                    {"order_id": regex_q},
                    {"plan_name": regex_q},
                    {"plan_id": regex_q},
                    {"gateway_transaction_id": regex_q},
                    {"external_transaction_id": regex_q},
                    {"provider_reference": regex_q}
                ]

        # Date range filters
        date_filter: Dict[str, Any] = {}
        if date_from:
            if isinstance(date_from, str):
                try:
                    df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                    date_filter["$gte"] = df
                except Exception:
                    pass
            elif isinstance(date_from, datetime):
                date_filter["$gte"] = date_from

        if date_to:
            if isinstance(date_to, str):
                try:
                    dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                    date_filter["$lte"] = dt
                except Exception:
                    pass
            elif isinstance(date_to, datetime):
                date_filter["$lte"] = date_to

        if date_filter:
            query["created_at"] = date_filter

        total = await db["payment_transactions"].count_documents(query)
        safe_page = max(1, page)
        safe_limit = min(max(1, limit), 1000)
        skip = (safe_page - 1) * safe_limit

        cursor = db["payment_transactions"].find(query).sort("created_at", -1).skip(skip).limit(safe_limit)

        items = []
        async for doc in cursor:
            p_id = doc.get("plan_id", "UNKNOWN")
            p_config = PLANS.get(p_id, {})
            p_credits = doc.get("credits_included") or doc.get("purchased_credits")
            if p_credits is None:
                cycle = doc.get("billing_cycle", "monthly")
                mult = 3 if cycle == "quarterly" else (12 if cycle == "yearly" else 1)
                p_credits = p_config.get("credits", 0) * mult

            created = doc.get("created_at")
            verified = doc.get("verified_at")
            cancelled = doc.get("cancelled_at")
            completed = doc.get("completed_at") or verified or cancelled or (doc.get("updated_at") if doc.get("status") in ["success", "failed", "cancelled", "expired", "refunded"] else None)

            provider_ref = doc.get("gateway_transaction_id") or doc.get("external_transaction_id") or doc.get("provider_reference") or doc.get("order_id")
            pub_tx_id = doc.get("transaction_id") or f"GROWG_{str(doc['_id'])[-6:]}"

            items.append({
                "id": str(doc["_id"]),
                "transaction_id": pub_tx_id,
                "public_transaction_id": pub_tx_id,
                "order_id": doc.get("order_id", ""),
                "provider_reference": provider_ref,
                "gateway_transaction_id": provider_ref,
                "external_transaction_id": doc.get("external_transaction_id"),
                "user_id": str(doc.get("user_id")),
                "user_name": doc.get("user_name"),
                "user_email": doc.get("user_email"),
                "user_phone": doc.get("user_phone"),
                "plan_id": p_id,
                "plan_name": doc.get("plan_name") or p_config.get("name", p_id),
                "plan_duration": doc.get("plan_duration") or doc.get("billing_cycle", "monthly"),
                "amount": float(doc.get("amount", 0.0)),
                "base_amount": doc.get("base_amount"),
                "gst_amount": doc.get("gst_amount"),
                "gst_rate": doc.get("gst_rate"),
                "gst_percentage": doc.get("gst_percentage", 18.0 if doc.get("gst_rate") else 0.0),
                "total_payable": doc.get("total_payable") or doc.get("amount"),
                "currency": doc.get("currency", "INR"),
                "payment_mode": doc.get("payment_mode") or "Unknown",
                "payment_gateway": doc.get("payment_gateway") or "Finunique Payin",
                "payment_provider": doc.get("payment_provider") or "Finunique",
                "billing_cycle": doc.get("billing_cycle", "monthly"),
                "status": doc.get("status", "pending"),
                "failure_reason": doc.get("failure_reason"),
                "refund_details": doc.get("refund_details"),
                "payment_url": doc.get("payment_url"),
                "upi_url": doc.get("upi_url"),
                "qr_code": doc.get("qr_code"),
                "purchased_credits": p_credits,
                "credits_included": p_credits,
                "credits_granted": p_credits if doc.get("status") == "success" else 0,
                "created_at": created,
                "completed_at": completed,
                "verified_at": verified,
                "cancelled_at": cancelled,
                "updated_at": doc.get("updated_at")
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
    async def get_transaction_by_id(
        db,
        user_id: str,
        transaction_id_or_order_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single transaction by GROWG transaction_id, order_id, or internal _id,
        strictly scoped to the authenticated user. Returns None if not found or unauthorized.
        """
        lookup_val = (transaction_id_or_order_id or "").strip()
        if not lookup_val:
            return None

        or_conditions = [
            {"transaction_id": lookup_val},
            {"transaction_id": lookup_val.upper()},
            {"order_id": lookup_val},
            {"order_id": lookup_val.upper()}
        ]
        if ObjectId.is_valid(lookup_val):
            or_conditions.append({"_id": ObjectId(lookup_val)})

        doc = await db["payment_transactions"].find_one({
            "user_id": str(user_id),
            "$or": or_conditions
        })
        if not doc:
            return None

        p_id = doc.get("plan_id", "UNKNOWN")
        p_config = PLANS.get(p_id, {})
        p_credits = doc.get("credits_included") or doc.get("purchased_credits")
        if p_credits is None:
            cycle = doc.get("billing_cycle", "monthly")
            mult = 3 if cycle == "quarterly" else (12 if cycle == "yearly" else 1)
            p_credits = p_config.get("credits", 0) * mult

        created = doc.get("created_at")
        verified = doc.get("verified_at")
        cancelled = doc.get("cancelled_at")
        completed = doc.get("completed_at") or verified or cancelled or (doc.get("updated_at") if doc.get("status") in ["success", "failed", "cancelled", "expired", "refunded"] else None)

        provider_ref = doc.get("gateway_transaction_id") or doc.get("external_transaction_id") or doc.get("provider_reference") or doc.get("order_id")
        pub_tx_id = doc.get("transaction_id") or f"GROWG_{str(doc['_id'])[-6:]}"

        return {
            "id": str(doc["_id"]),
            "transaction_id": pub_tx_id,
            "public_transaction_id": pub_tx_id,
            "order_id": doc.get("order_id", ""),
            "provider_reference": provider_ref,
            "gateway_transaction_id": provider_ref,
            "external_transaction_id": doc.get("external_transaction_id"),
            "user_id": str(doc.get("user_id")),
            "user_name": doc.get("user_name"),
            "user_email": doc.get("user_email"),
            "user_phone": doc.get("user_phone"),
            "plan_id": p_id,
            "plan_name": doc.get("plan_name") or p_config.get("name", p_id),
            "plan_duration": doc.get("plan_duration") or doc.get("billing_cycle", "monthly"),
            "amount": float(doc.get("amount", 0.0)),
            "base_amount": doc.get("base_amount"),
            "gst_amount": doc.get("gst_amount"),
            "gst_rate": doc.get("gst_rate"),
            "gst_percentage": doc.get("gst_percentage", 18.0 if doc.get("gst_rate") else 0.0),
            "total_payable": doc.get("total_payable") or doc.get("amount"),
            "currency": doc.get("currency", "INR"),
            "payment_mode": doc.get("payment_mode") or "Unknown",
            "payment_gateway": doc.get("payment_gateway") or "Finunique Payin",
            "payment_provider": doc.get("payment_provider") or "Finunique",
            "billing_cycle": doc.get("billing_cycle", "monthly"),
            "status": doc.get("status", "pending"),
            "failure_reason": doc.get("failure_reason"),
            "refund_details": doc.get("refund_details"),
            "payment_url": doc.get("payment_url"),
            "upi_url": doc.get("upi_url"),
            "qr_code": doc.get("qr_code"),
            "purchased_credits": p_credits,
            "credits_included": p_credits,
            "credits_granted": p_credits if doc.get("status") == "success" else 0,
            "created_at": created,
            "completed_at": completed,
            "verified_at": verified,
            "cancelled_at": cancelled,
            "updated_at": doc.get("updated_at")
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
