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
    async def create_payment(db, user_id: str, user_email: str, plan_id: str, billing_cycle: str = "monthly") -> Dict[str, Any]:
        normalized_plan_id = plan_id.upper().strip()
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
            amount_inr = float(cycle_pricing["price"])
        else:
            amount_inr = float(plan["price"])
            
        if not settings.PAYIN_URL or not settings.PAYIN_TOKEN:
            raise HTTPException(status_code=500, detail="Finunique Payin configuration missing")

        order_id = f"ORDER_{uuid.uuid4().hex[:12].upper()}"
        
        now = datetime.now(timezone.utc)
        transaction = {
            "user_id": user_id,
            "plan_id": normalized_plan_id,
            "plan_name": plan["name"],
            "billing_cycle": cycle,
            "amount": amount_inr,
            "currency": plan.get("currency", "INR"),
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
    async def process_callback(db, payload: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
        order_id = payload.get("orderId") or payload.get("reference")
        if not order_id:
            raise HTTPException(status_code=400, detail="Missing orderId")
            
        transaction = await db["payment_transactions"].find_one({"order_id": order_id})
        if not transaction:
            raise HTTPException(status_code=404, detail="Unknown order")
            
        if transaction.get("status") == "success":
            return {"success": True, "status": "success", "message": "Already processed"}
            
        response_code = str(payload.get("responseCode", "")).strip().upper()
        payload_status = str(payload.get("status", "")).strip().upper()
        now = datetime.now(timezone.utc)
        
        is_success = (response_code == "100" or payload_status in ["SUCCESS", "PAID"])
        
        if is_success:
            payload_amount = float(payload.get("amount", 0))
            transaction_amount = float(transaction["amount"])
            
            amount_matches = False
            if abs(payload_amount - transaction_amount) < 0.01 or \
               abs(payload_amount - transaction_amount * 100) < 0.01 or \
               abs(payload_amount / 100 - transaction_amount) < 0.01:
                amount_matches = True
                
            if not amount_matches:
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "failed", "failure_reason": f"Amount mismatch: received {payload_amount}, expected {transaction_amount}", "updated_at": now}}
                )
                return {"success": False, "status": "failed", "message": "Amount mismatch"}
                
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {
                    "status": "success", 
                    "external_transaction_id": payload.get("pgTransId") or payload.get("txnId"),
                    "verified_at": now,
                    "updated_at": now
                }}
            )
            
            cycle = transaction.get("billing_cycle", "monthly")
            await SubscriptionService.upgrade_plan(
                db, 
                transaction["user_id"], 
                transaction["plan_id"],
                billing_cycle=cycle
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
            
        elif response_code in ["101", "PENDING"] or payload_status in ["PENDING"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "pending", "failure_reason": payload.get("responseDescription", "Payment pending"), "updated_at": now}}
            )
            return {"success": False, "status": "pending", "message": "Payment pending"}
            
        elif response_code in ["103", "CANCELLED", "CANCELED"] or payload_status in ["CANCELLED", "CANCELED"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "cancelled", "failure_reason": payload.get("responseDescription", "Payment cancelled by user"), "updated_at": now}}
            )
            return {"success": False, "status": "cancelled", "message": "Payment cancelled"}
            
        elif response_code in ["104", "EXPIRED"] or payload_status in ["EXPIRED"]:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "expired", "failure_reason": payload.get("responseDescription", "Payment expired"), "updated_at": now}}
            )
            return {"success": False, "status": "expired", "message": "Payment expired"}
            
        else:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {"$set": {"status": "failed", "failure_reason": payload.get("responseDescription", "Payment failed"), "updated_at": now}}
            )
            return {"success": False, "status": "failed", "message": "Payment failed"}
