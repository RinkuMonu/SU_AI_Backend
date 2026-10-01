import json
import uuid
import httpx
from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import HTTPException
from app.core.config import settings
from app.core.billing_config import PLANS
from app.services.subscription_service import SubscriptionService

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
        amount_inr = float(plan["price"])
        
        now = datetime.now(timezone.utc)
        transaction = {
            "user_id": user_id,
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "amount": amount_inr,
            "currency": plan["currency"],
            "order_id": order_id,
            "status": "pending",
            "created_at": now,
            "updated_at": now
        }
        await db["payment_transactions"].insert_one(transaction)

        payload = {
            "amount": amount_inr,
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
                    timeout=15.0
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
                    payment_url = data["data"].get("redirectURL")
                
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
            raise HTTPException(status_code=400, detail="Missing orderId")
            
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            raise HTTPException(status_code=404, detail="Unknown order")
            
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
            
            await SubscriptionService.upgrade_plan(db, transaction["user_id"], transaction["plan_id"])
            return {"success": True, "status": "success", "message": "Payment verified"}
        
        else:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": payload.get("responseDescription", "Failed"), "updated_at": datetime.now(timezone.utc)}}
            )
            return {"success": False, "status": "failed", "message": "Payment failed"}
