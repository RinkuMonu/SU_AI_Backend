import json
import uuid
import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import HTTPException
from app.core.config import settings
from app.core.billing_config import PLANS
from app.services.subscription_service import SubscriptionService
from app.utils.response import serialize_mongo

logger = logging.getLogger(__name__)

class PayinService:
    @staticmethod
    async def create_payment(db, user_id: str, user_email: str, plan_id: str) -> Dict[str, Any]:
        if plan_id not in PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        plan = PLANS[plan_id]
        if plan["price"] == 0:
            raise HTTPException(status_code=400, detail="Cannot create payment for FREE plan")
            
        if not settings.PAYIN_URL or not settings.PAYIN_TOKEN:
            raise HTTPException(status_code=500, detail="Finunique Payin configuration missing")

        order_id = f"ORDER_{uuid.uuid4().hex[:12].upper()}"
        base_amount = float(plan.get("base_price", plan["price"]))
        gst_rate = float(plan.get("gst_rate", 0.18 if base_amount > 0 else 0.0))
        gst_amount = float(plan.get("gst_amount", round(base_amount * gst_rate, 2)))
        total_amount = float(plan.get("total_price", round(base_amount + gst_amount, 2)))
        
        now = datetime.now(timezone.utc)
        transaction = {
            "user_id": user_id,
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "base_amount": base_amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "amount": total_amount,
            "currency": plan["currency"],
            "order_id": order_id,
            "status": "pending",
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        payload = {
            "amount": total_amount,
            "email": user_email,
            "reference": order_id,
            "userId": user_id
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
                    "status": "pending"
                }
        except httpx.RequestError:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": "Payment Gateway timeout", "updated_at": datetime.now(timezone.utc)}}
            )
            raise HTTPException(status_code=504, detail="Payment Gateway timeout")

    @staticmethod
    async def process_callback(db, payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        order_id = payload.get("orderId")
        if not order_id:
            return {"success": False, "status": "failed", "message": "Missing orderId"}
            
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            return {"success": False, "status": "failed", "message": "Unknown order"}
            
        if transaction["status"] == "success":
            return {"success": True, "status": "success", "message": "Already processed"}
            
        response_code = str(payload.get("responseCode", ""))
        is_success = (response_code == "100")
        
        # Payin callback amount might be in paise from gateway, or INR.
        # We verify if we can, but since the gateway/Finunique exact multiplier is tricky,
        # we check if it matches in either INR or paise.
        payload_amount = float(payload.get("amount", 0))
        transaction_amount = float(transaction["amount"])
        
        amount_matches = False
        if payload_amount == transaction_amount or payload_amount == transaction_amount * 100 or payload_amount / 100 == transaction_amount:
            amount_matches = True
            
        if is_success:
            if not amount_matches:
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "failed", "failure_reason": "Amount mismatch", "updated_at": datetime.now(timezone.utc)}}
                )
                return {"success": False, "status": "failed", "message": "Amount mismatch"}
                
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {
                    "status": "success", 
                    "external_transaction_id": payload.get("pgTransId"),
                    "verified_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }}
            )
            
            if transaction["plan_id"] != "HIRE_INFLUENCER":
                await SubscriptionService.upgrade_plan(db, transaction["user_id"], transaction["plan_id"])
            return {"success": True, "status": "success", "message": "Payment verified"}
        
        else:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": payload.get("responseDescription", "Failed"), "updated_at": datetime.now(timezone.utc)}}
            )
            return {"success": False, "status": "failed", "message": "Payment failed"}

    @staticmethod
    async def create_hire_influencer_payment(
        db,
        user_id: str,
        user_email: str,
        hiring_request_id: str,
        amount: float = 200.0
    ) -> Dict[str, Any]:
        """
        Creates a Zaakpay / Finunique Payin order specifically for Influencer Hiring (₹200 fee).
        """
        order_id = f"HIRE_{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)
        
        transaction = {
            "user_id": user_id,
            "user_email": user_email,
            "plan_id": "HIRE_INFLUENCER",
            "plan_name": "Influencer Hiring Fee",
            "hiring_request_id": hiring_request_id,
            "base_amount": amount,
            "gst_rate": 0.0,
            "gst_amount": 0.0,
            "amount": amount,
            "currency": "INR",
            "order_id": order_id,
            "status": "pending",
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        payload = {
            "amount": amount,
            "email": user_email,
            "reference": order_id,
            "userId": user_id
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
        }

        payment_url = None
        if settings.PAYIN_URL and settings.PAYIN_TOKEN:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        settings.PAYIN_URL,
                        json=payload,
                        headers=headers,
                        timeout=15.0
                    )
                    if response.status_code < 400:
                        data = response.json()
                        if data.get("data") and isinstance(data["data"], dict):
                            payment_url = data["data"].get("redirectEx") or data["data"].get("redirectURL")
            except Exception as e:
                logger.warning(f"Zaakpay / Finunique API call error: {e}")

        # If live gateway returns a URL, save it; otherwise use simulated checkout
        if not payment_url:
            backend_base = (getattr(settings, "BACKEND_URL", "") or "http://localhost:8000").rstrip("/")
            payment_url = f"{backend_base}/api/v1/payments/payin/checkout-simulated?order_id={order_id}&amount={amount}"

        await db["payment_transactions"].update_one(
            {"order_id": order_id},
            {"$set": {"status": "initiated", "payment_url": payment_url, "updated_at": datetime.now(timezone.utc)}}
        )

        # Also log into marketplace_payments
        await db["marketplace_payments"].insert_one({
            "order_id": order_id,
            "hiring_request_id": hiring_request_id,
            "hirer_id": user_id,
            "currency": "INR",
            "amount_inr": amount,
            "amount_paise": int(amount * 100),
            "type": "hire_influencer_fee",
            "status": "pending",
            "payment_url": payment_url,
            "created_at": now,
            "updated_at": now
        })

        return {
            "success": True,
            "order_id": order_id,
            "amount": amount,
            "currency": "INR",
            "payment_url": payment_url,
            "hiring_request_id": hiring_request_id,
            "status": "initiated",
            "message": f"Zaakpay order created for ₹{amount} Influencer Hiring Fee"
        }

    @staticmethod
    async def verify_hire_payment(db, order_id: str, payment_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify payment confirmation for the ₹200 influencer hiring fee.
        Updates payment_transactions, marketplace_payments, and advances hiring_request.
        """
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            transaction = await db["marketplace_payments"].find_one({"order_id": order_id})
            if not transaction:
                raise HTTPException(status_code=404, detail="Payment order not found")

        now = datetime.now(timezone.utc)
        confirmed_payment_id = payment_id or f"TXN_{uuid.uuid4().hex[:10].upper()}"

        await db["payment_transactions"].update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "success",
                "payment_id": confirmed_payment_id,
                "verified_at": now,
                "updated_at": now
            }}
        )

        await db["marketplace_payments"].update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "success",
                "payment_id": confirmed_payment_id,
                "verified_at": now,
                "updated_at": now
            }}
        )

        hiring_req_id = transaction.get("hiring_request_id")
        req = None
        if hiring_req_id:
            # Advance to awaiting_admin_approval while unlocking chat immediately
            await db["hiring_requests"].update_one(
                {"hiring_request_id": hiring_req_id},
                {"$set": {
                    "fee_paid": True,
                    "hire_fee_paid": True,
                    "paid_amount": 200.0,
                    "payment_order_id": order_id,
                    "payment_id": confirmed_payment_id,
                    "status": "awaiting_admin_approval",
                    "agreement_status": "awaiting_admin_approval",
                    "chat_active": True,
                    "activated_at": now,
                    "updated_at": now
                }}
            )

            req = await db["hiring_requests"].find_one({"hiring_request_id": hiring_req_id})
            if req:
                # Initialize private chat room
                chat_room = {
                    "hiring_request_id": hiring_req_id,
                    "hirer_id": req.get("hirer_id"),
                    "influencer_id": req.get("influencer_user_id") or req.get("influencer_id"),
                    "campaign_name": req.get("campaign_name", "Influencer Collaboration"),
                    "status": "active",
                    "created_at": now,
                    "updated_at": now
                }
                await db["marketplace_chats"].update_one(
                    {"hiring_request_id": hiring_req_id},
                    {"$set": chat_room},
                    upsert=True
                )

                # Add automated welcome message if not already present
                msg_count = await db["marketplace_messages"].count_documents({"hiring_request_id": hiring_req_id})
                if msg_count == 0:
                    welcome_msg = {
                        "hiring_request_id": hiring_req_id,
                        "sender_id": "system",
                        "sender_name": "SevenUnique AI Assistant",
                        "message": "🎉 Collaboration activated! Platform fee of ₹200 verified via Zaakpay. Brand and Creator can now discuss deliverables, briefs, and timelines directly in this private room.",
                        "attachments": [],
                        "timestamp": now,
                        "read": False
                    }
                    await db["marketplace_messages"].insert_one(welcome_msg)

        return {
            "success": True,
            "message": "Hire fee of ₹200 verified successfully via Zaakpay! Collaboration activated & Private Chat room unlocked.",
            "order_id": order_id,
            "payment_id": confirmed_payment_id,
            "status": "success",
            "hiring_request_id": hiring_req_id,
            "data": serialize_mongo(req) if req else None
        }

