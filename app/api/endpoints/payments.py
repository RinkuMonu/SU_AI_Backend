from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Any, Dict
from app.api.dependencies import get_current_user, get_database
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentCallbackResponse,
    PaymentStatusResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
)
from app.services.payin_service import PayinService
from pymongo.database import Database

router = APIRouter()

@router.post("/payin/create", response_model=PaymentCreateResponse)
async def create_payment(
    request: PaymentCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    user_id = str(current_user["id"])
    user_email = current_user.get("email", "user@example.com")
    result = await PayinService.create_payment(
        db, user_id, user_email, request.plan_id, billing_cycle=request.billing_cycle
    )
    return result

@router.post("/payin/callback", response_model=PaymentCallbackResponse)
@router.get("/payin/callback", response_model=PaymentCallbackResponse)
@router.post("/payin/webhook", response_model=PaymentCallbackResponse)
@router.get("/payin/webhook", response_model=PaymentCallbackResponse)
async def payment_callback(
    request: Request,
    db: Database = Depends(get_database)
):
    payload: Dict[str, Any] = {}
    if request.method == "GET":
        payload = dict(request.query_params)
    else:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        else:
            try:
                form = await request.form()
                payload = dict(form)
            except Exception:
                payload = {}
        # If payload was empty in body, check query params
        if not payload and request.query_params:
            payload = dict(request.query_params)

    headers = dict(request.headers)
    result = await PayinService.process_callback(db, payload, headers)
    return result

@router.post("/payin/verify", response_model=PaymentVerifyResponse)
async def verify_payment(
    request: PaymentVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Client-triggered official server-side verification with the Payin provider.
    Verifies transaction status, activates plan if successful, and returns result.
    """
    order_id = request.order_id.strip()
    transaction = await db["payment_transactions"].find_one({"order_id": order_id})
    if not transaction:
        raise HTTPException(status_code=404, detail="Order not found")

    user_id = str(current_user.get("id") or current_user.get("_id"))
    if transaction["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to verify this order")

    # If already confirmed, return success immediately
    if transaction.get("status") == "success":
        return PaymentVerifyResponse(
            success=True,
            status="success",
            order_id=order_id,
            verified=True,
            plan_id=transaction.get("plan_id"),
            amount=transaction.get("amount"),
            message="Payment already verified and subscription is active"
        )

    # Perform official server-side check with Finunique provider
    result = await PayinService.verify_payment_with_provider(db, order_id)
    return PaymentVerifyResponse(
        success=result.get("success", False),
        status=result.get("status", transaction.get("status", "pending")),
        order_id=order_id,
        verified=result.get("verified", False),
        plan_id=transaction.get("plan_id"),
        amount=transaction.get("amount"),
        message=result.get("message", "Payment verification completed")
    )

@router.get("/payin/status/{order_id}", response_model=PaymentStatusResponse)
async def payment_status(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    transaction = await db["payment_transactions"].find_one({"order_id": order_id})
    if not transaction:
        raise HTTPException(status_code=404, detail="Order not found")

    user_id = str(current_user.get("id") or current_user.get("_id"))
    if transaction["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # If pending or initiated, attempt server-side verification check
    if transaction.get("status") in ["pending", "initiated"]:
        try:
            await PayinService.verify_payment_with_provider(db, order_id)
            refreshed = await db["payment_transactions"].find_one({"order_id": order_id})
            if refreshed:
                transaction = refreshed
        except Exception:
            pass

    return {
        "order_id": order_id,
        "status": transaction["status"],
        "amount": transaction["amount"],
        "base_amount": transaction.get("base_amount"),
        "gst_amount": transaction.get("gst_amount")
    }


