import json
import uuid
import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import HTTPException
from pymongo.collection import ReturnDocument
from app.core.config import settings
from app.core.billing_config import PLANS
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

class PayinService:
    @staticmethod
    async def create_payment(db, user_id: str, user_email: str, plan_id: str, billing_cycle: str = "monthly") -> Dict[str, Any]:
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
        
        now = datetime.now(timezone.utc)
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
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        callback_url = getattr(settings, "PAYIN_CALLBACK_URL", None) or f"{(settings.BACKEND_URL or 'https://api.dhandagrow.com').rstrip('/')}/api/v1/payments/payin/callback"
        frontend_url = (settings.FRONTEND_URL or "https://dhandagrow.com").rstrip("/")
        redirect_url = f"{frontend_url}/subscription?order_id={order_id}"

        payload = {
            "amount": total_amount,
            "email": user_email,
            "reference": order_id,
            "userId": user_id,
            "callback_url": callback_url,
            "callbackUrl": callback_url,
            "redirect_url": redirect_url,
            "redirectURL": redirect_url,
        }
        
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
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "failed", "failure_reason": f"Payin API error: {response.status_code}", "updated_at": datetime.now(timezone.utc)}}
                    )
                    raise HTTPException(status_code=502, detail="Payment Gateway API failed")
                    
                data = response.json()
                
                payment_url = None
                if data.get("data") and isinstance(data["data"], dict):
                    # Use redirectEx for the web checkout gateway instead of upi:// intent
                    payment_url = data["data"].get("redirectEx") or data["data"].get("redirectURL")
                
                if not payment_url:
                    await db["payment_transactions"].update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "failed", "failure_reason": "Missing redirectURL in Payin response", "updated_at": datetime.now(timezone.utc)}}
                    )
                    raise HTTPException(status_code=502, detail="Invalid Payment Gateway response")
                
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "initiated", "payment_url": payment_url, "updated_at": datetime.now(timezone.utc)}}
                )
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "payment_url": payment_url,
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

        status_url = getattr(settings, "PAYIN_STATUS_URL", None) or (
            settings.PAYIN_URL.replace("/payin", "/status") if settings.PAYIN_URL else None
        )
        if not status_url or not getattr(settings, "PAYIN_TOKEN", None):
            return {
                "success": False,
                "status": transaction.get("status", "pending"),
                "order_id": order_id,
                "verified": False,
                "message": "Payin verification endpoint not configured"
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
        }
        payload = {
            "reference": order_id,
            "orderId": order_id
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(status_url, json=payload, headers=headers)
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
            
            amount_matches = False
            if abs(payload_amount - transaction_amount) < 0.05 or \
               abs(payload_amount - transaction_amount * 100) < 5.0 or \
               abs(payload_amount / 100 - transaction_amount) < 0.05:
                amount_matches = True
                
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
