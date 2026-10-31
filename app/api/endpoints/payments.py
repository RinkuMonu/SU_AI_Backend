from fastapi import APIRouter, Depends, Request, HTTPException, Query, Header, Response, status
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from pymongo.database import Database

from app.api.dependencies import get_current_user, get_database, _extract_user_id
from app.core.security import get_current_user_optional, decode_access_token
from app.services.invoice_service import InvoiceService
from app.services.pdf_service import PDFService
from app.schemas.payment import (
    CashfreeSubscriptionCreateRequest,
    CashfreeSubscriptionResponse,
    CashfreeSubscriptionStatusResponse,
    CashfreeSubscriptionVerifyRequest,
    WebhookResponse,
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
from app.services.cashfree_service import CashfreeService

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


# ---------------------------------------------------------------------------
# Cashfree Subscriptions & AutoPay (Recurring) Endpoints
# ---------------------------------------------------------------------------

@router.post("/subscription/create", response_model=CashfreeSubscriptionResponse)
async def create_subscription(
    request: CashfreeSubscriptionCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Create a Cashfree recurring subscription mandate with actual plan authorization charge.
    Returns session/payment URL to open Cashfree Checkout.
    """
    user_id = str(current_user.get("id") or current_user.get("_id") or "")
    user_email = current_user.get("email", "user@example.com")
    user_name = current_user.get("name") or current_user.get("fullName") or "Subscriber"
    user_phone = request.customer_phone or current_user.get("phone") or current_user.get("phone_number")

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
    try:
        raw_body = await request.body()
        payload = await request.json()
    except Exception:
        raw_body = b""
        payload = {}

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
    user_id = str(current_user.get("id") or current_user.get("_id") or "")
    result = await CashfreeService.get_subscription_status(
        db=db,
        subscription_id=subscription_id,
        current_user_id=user_id
    )
    return result


@router.post("/subscription/verify", response_model=CashfreeSubscriptionStatusResponse)
async def verify_subscription(
    request: CashfreeSubscriptionVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Verify and sync subscription mandate status for an authenticated user.
    """
    sub_id = request.subscription_id or request.order_id
    if not sub_id:
        raise HTTPException(status_code=400, detail="subscription_id or order_id is required")
    user_id = str(current_user.get("id") or current_user.get("_id") or "")
    return await CashfreeService.get_subscription_status(
        db=db,
        subscription_id=sub_id,
        current_user_id=user_id
    )


@router.get("/transactions/{transaction_id}/receipt")
async def download_transaction_receipt_alias(
    transaction_id: str,
    token: Optional[str] = Query(None, description="Secure download token from invoice email"),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    db: Database = Depends(get_database)
):
    """
    Generates and returns an official branded PDF receipt / tax invoice for a transaction.
    Accessible with authenticated user ownership OR valid secure token from invoice email link.
    """
    from bson import ObjectId
    clean_id = (transaction_id or "").strip()
    query = [
        {"transaction_id": clean_id},
        {"transaction_id": clean_id.upper()},
        {"order_id": clean_id},
        {"order_id": clean_id.upper()}
    ]
    if ObjectId.is_valid(clean_id):
        query.append({"_id": ObjectId(clean_id)})

    tx = await db["payment_transactions"].find_one({"$or": query})
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found."
        )

    # 1. Check secure token authentication
    has_valid_token = False
    if token:
        clean_tok = token.strip()
        pub_tx = tx.get("transaction_id") or clean_id
        ord_id = tx.get("order_id") or clean_id
        if InvoiceService.verify_secure_token(clean_tok, pub_tx, ord_id) or clean_tok == tx.get("invoice_download_token"):
            has_valid_token = True
        else:
            jwt_payload = decode_access_token(clean_tok)
            if jwt_payload and str(jwt_payload.get("sub")) == str(tx.get("user_id")):
                has_valid_token = True

    # 2. Check authenticated user session
    if not has_valid_token:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required or valid invoice download token missing."
            )
        user_id = _extract_user_id(current_user)
        if str(tx.get("user_id")) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to download this receipt."
            )

    if not tx.get("invoice_number"):
        tx = await InvoiceService.ensure_invoice_record(db, tx)

    if current_user:
        if not tx.get("user_name") or tx.get("user_name") == "Valued Customer":
            tx["user_name"] = current_user.get("name") or current_user.get("full_name") or "Valued Customer"
        if not tx.get("user_email") or tx.get("user_email") == "N/A":
            tx["user_email"] = current_user.get("email") or "N/A"
        if not tx.get("user_phone") or tx.get("user_phone") == "N/A":
            tx["user_phone"] = current_user.get("phone_number") or current_user.get("mobile") or "N/A"

    pdf_bytes = PDFService.generate_receipt_pdf(tx)
    pub_id = tx.get("transaction_id") or tx.get("order_id") or tx.get("invoice_number") or "receipt"
    filename = f"receipt_{pub_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf"
        }
    )


@router.post("/transactions/{transaction_id}/resend-invoice-email")
async def resend_invoice_email_alias(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Retries sending the MSG91 invoice email for a successful transaction.
    Safe and idempotent: Reuses existing invoice number without generating duplicate records.
    """
    user_id = _extract_user_id(current_user)
    return await InvoiceService.retry_invoice_email(
        db,
        transaction_id_or_order_id=transaction_id,
        authenticated_user_id=user_id
    )


@router.get("/transactions/{transaction_id}/invoice-status")
async def get_invoice_email_status_alias(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Returns invoice number, secure download URL, and MSG91 email delivery audit status for a transaction.
    """
    user_id = _extract_user_id(current_user)
    clean_id = (transaction_id or "").strip()
    from bson import ObjectId
    query = [
        {"transaction_id": clean_id},
        {"transaction_id": clean_id.upper()},
        {"order_id": clean_id},
        {"order_id": clean_id.upper()}
    ]
    if ObjectId.is_valid(clean_id):
        query.append({"_id": ObjectId(clean_id)})

    tx = await db["payment_transactions"].find_one({"$or": query})
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transaction '{transaction_id}' not found.")
    if str(tx.get("user_id")) != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: You do not own this transaction.")

    return {
        "success": True,
        "transaction_id": tx.get("transaction_id"),
        "order_id": tx.get("order_id"),
        "invoice_number": tx.get("invoice_number") or InvoiceService.generate_invoice_number(tx),
        "invoice_download_url": tx.get("invoice_download_url"),
        "status": tx.get("status"),
        "email_delivery": {
            "sent": tx.get("invoice_email_sent", False),
            "status": tx.get("invoice_email_status", "NOT_SENT"),
            "recipient": tx.get("invoice_email_recipient") or tx.get("user_email"),
            "sent_at": tx.get("invoice_email_sent_at"),
            "attempts": tx.get("invoice_email_attempts", 0),
            "last_error": tx.get("invoice_email_last_error"),
            "last_attempt_at": tx.get("invoice_email_last_attempt_at")
        }
    }


@router.post("/transactions/{transaction_id}/resend-failed-email")
async def resend_payment_failed_email(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Retries sending the MSG91 payment failed notification email for an unsuccessful transaction.
    """
    user_id = _extract_user_id(current_user)
    return await InvoiceService.retry_payment_failed_email(
        db,
        transaction_id_or_order_id=transaction_id,
        authenticated_user_id=user_id
    )


@router.get("/transactions/{transaction_id}/failed-email-status")
async def get_payment_failed_email_status(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    """
    Returns payment failed notification email delivery status for a transaction.
    """
    user_id = _extract_user_id(current_user)
    clean_id = (transaction_id or "").strip()
    from bson import ObjectId
    query = [
        {"transaction_id": clean_id},
        {"transaction_id": clean_id.upper()},
        {"order_id": clean_id},
        {"order_id": clean_id.upper()}
    ]
    if ObjectId.is_valid(clean_id):
        query.append({"_id": ObjectId(clean_id)})

    tx = await db["payment_transactions"].find_one({"$or": query})
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transaction '{transaction_id}' not found.")
    if str(tx.get("user_id")) != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: You do not own this transaction.")

    return {
        "success": True,
        "transaction_id": tx.get("transaction_id"),
        "order_id": tx.get("order_id"),
        "status": tx.get("status"),
        "failure_reason": tx.get("failure_reason"),
        "failed_email_delivery": {
            "sent": tx.get("payment_failed_email_sent", False),
            "status": tx.get("payment_failed_email_status", "NOT_SENT"),
            "recipient": tx.get("payment_failed_email_recipient") or tx.get("user_email"),
            "sent_at": tx.get("payment_failed_email_sent_at"),
            "attempts": tx.get("payment_failed_email_attempts", 0),
            "last_error": tx.get("payment_failed_email_last_error")
        }
    }
