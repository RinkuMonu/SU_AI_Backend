from fastapi import APIRouter, Depends, Request, HTTPException, Query
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from pymongo.database import Database

from app.api.dependencies import get_current_user, get_database
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentCallbackResponse,
    PaymentStatusResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    PaymentCancelRequest,
    PaymentCancelResponse,
    PaymentTransactionItem,
    PaymentTransactionListResponse,
    TestPlanResetRequest,
    TestPlanResetResponse,
)
from app.services.payin_service import PayinService

router = APIRouter()

@router.post("/payin/create", response_model=PaymentCreateResponse)
async def create_payment(
    request: PaymentCreateRequest,
    raw_req: Request,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    user_id = str(current_user.get("id") or current_user.get("_id") or "")
    raw_email = current_user.get("email")
    user_email = raw_email.strip() if isinstance(raw_email, str) else ""
    user_name = current_user.get("name") or current_user.get("fullName") or "User"
    user_mobile = current_user.get("phone_number") or current_user.get("phone")

    # Detect caller's origin/referer so gateway redirects back to where user is (e.g. localhost:3000)
    origin = raw_req.headers.get("origin") or raw_req.headers.get("referer") or ""
    caller_frontend_url = None
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if parsed.scheme and parsed.netloc:
            caller_frontend_url = f"{parsed.scheme}://{parsed.netloc}"

    result = await PayinService.create_payment(
        db,
        user_id,
        user_email,
        request.plan_id,
        billing_cycle=request.billing_cycle,
        user_name=user_name,
        user_mobile=user_mobile,
        frontend_url=caller_frontend_url
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
            provider_reference=transaction.get("provider_reference") or transaction.get("external_transaction_id"),
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
        provider_reference=transaction.get("provider_reference") or transaction.get("external_transaction_id"),
        message=result.get("message", "Payment verification completed")
    )

@router.post("/payin/verify/{order_id}", response_model=PaymentVerifyResponse)
@router.get("/payin/verify/{order_id}", response_model=PaymentVerifyResponse)
async def verify_payment_by_path(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    return await verify_payment(PaymentVerifyRequest(order_id=order_id), current_user=current_user, db=db)

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

    can_cancel = transaction.get("status") in ["initiated", "pending"]
    return {
        "order_id": order_id,
        "status": transaction["status"],
        "can_cancel": can_cancel,
        "amount": transaction["amount"],
        "base_amount": transaction.get("base_amount"),
        "gst_amount": transaction.get("gst_amount"),
        "currency": transaction.get("currency", "INR"),
        "plan_id": transaction.get("plan_id"),
        "plan_name": transaction.get("plan_name"),
        "provider_reference": transaction.get("provider_reference") or transaction.get("external_transaction_id"),
        "created_at": transaction.get("created_at"),
        "verified_at": transaction.get("verified_at"),
        "message": "Payment verified and subscription is active" if transaction.get("status") == "success" else (transaction.get("failure_reason") or "Payment pending")
    }

@router.post("/payin/cancel", response_model=PaymentCancelResponse)
@router.post("/payin/cancel/{order_id}", response_model=PaymentCancelResponse)
async def cancel_payment_endpoint(
    request: Optional[PaymentCancelRequest] = None,
    order_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Cancels a pending payment order upon user cancellation or back-navigation.
    Refuses cancellation if payment already succeeded or verified with provider.
    """
    target_order_id = (order_id or (request.order_id if request else "")).strip()
    if not target_order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    user_id = str(current_user.get("id") or current_user.get("_id"))
    reason = request.reason if request and request.reason else "User navigated back or cancelled payment"

    result = await PayinService.cancel_payment(db, user_id, target_order_id, reason)
    return PaymentCancelResponse(**result)

@router.get("/transactions", response_model=PaymentTransactionListResponse)
@router.get("/history", response_model=PaymentTransactionListResponse)
async def get_user_transactions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (success, pending, cancelled, failed)"),
    payment_mode: Optional[str] = Query(None, description="Filter by payment mode"),
    search: Optional[str] = Query(None, description="Search query"),
    date_from: Optional[str] = Query(None, description="Date from"),
    date_to: Optional[str] = Query(None, description="Date to"),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Returns authenticated user-scoped payment transactions history with pagination and date sorting.
    Preserves all historical attempts including cancelled and failed transactions.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    return await PayinService.get_user_transactions(
        db,
        user_id,
        page=page,
        limit=limit,
        status=status,
        payment_mode=payment_mode,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )

@router.post("/test-plan/reset", response_model=TestPlanResetResponse)
async def reset_test_plan_endpoint(
    request: Optional[TestPlanResetRequest] = None,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Safely resets a test user's ₹1 TEST_PLAN subscription and entitlements.
    Preserves genuinely paid transactions for audit integrity while allowing repeated test flows.
    """
    caller_id = str(current_user.get("id") or current_user.get("_id"))
    caller_role = str(current_user.get("role", "")).lower()

    target_user_id = caller_id
    admin_override = False

    if request and request.target_user_id:
        if caller_role in ["admin", "administrator", "superuser"]:
            target_user_id = request.target_user_id.strip()
            admin_override = True
        elif request.target_user_id.strip() != caller_id:
            raise HTTPException(status_code=403, detail="Only administrators can reset test plans for other users.")

    result = await PayinService.reset_test_subscription(db, target_user_id, admin_override=admin_override)
    return TestPlanResetResponse(**result)
