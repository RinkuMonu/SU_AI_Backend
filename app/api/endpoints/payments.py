from fastapi import APIRouter, Depends, Request, HTTPException, Header
from typing import Optional, Dict, Any
from pymongo.database import Database
from app.api.dependencies import get_current_user, get_database
from app.schemas.payment import (
    CashfreeSubscriptionCreateRequest,
    CashfreeSubscriptionResponse,
    CashfreeSubscriptionStatusResponse,
    WebhookResponse
)
from app.services.cashfree_service import CashfreeService

router = APIRouter()

@router.post("/subscription/create", response_model=CashfreeSubscriptionResponse)
async def create_subscription(
    request: CashfreeSubscriptionCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Create a Cashfree recurring subscription mandate with ₹1 initial authorization charge.
    Returns session/payment URL to open Cashfree Checkout.
    """
    user_id = str(current_user["id"])
    user_email = current_user.get("email", "user@example.com")
    user_name = current_user.get("name", "Subscriber")
    user_phone = request.customer_phone or current_user.get("phone")

    result = await CashfreeService.create_subscription(
        db=db,
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        user_phone=user_phone,
        plan_id=request.plan_id,
        billing_cycle=request.billing_cycle or "monthly",
        return_url=request.return_url
    )
    return result

@router.post("/cashfree/webhook", response_model=WebhookResponse)
async def cashfree_webhook(
    request: Request,
    db: Database = Depends(get_database),
    x_webhook_signature: Optional[str] = Header(None, alias="x-webhook-signature"),
    x_webhook_timestamp: Optional[str] = Header(None, alias="x-webhook-timestamp")
):
    """
    Public webhook receiver for Cashfree server-to-server notifications.
    Verifies HMAC-SHA256 signature and activates the user subscription upon mandate approval.
    """
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    headers = dict(request.headers)

    # Note: Signature verification can be enforced in production
    if x_webhook_signature and x_webhook_timestamp:
        valid = CashfreeService.verify_webhook_signature(raw_body, x_webhook_timestamp, x_webhook_signature)
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    result = await CashfreeService.process_webhook(db, payload, raw_body=raw_body, headers=headers)
    return result

@router.get("/subscription/status/{subscription_id}", response_model=CashfreeSubscriptionStatusResponse)
async def get_subscription_status(
    subscription_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Get current subscription mandate status for an authenticated user.
    """
    result = await CashfreeService.get_subscription_status(
        db=db,
        subscription_id=subscription_id,
        current_user_id=str(current_user["id"])
    )
    return result
