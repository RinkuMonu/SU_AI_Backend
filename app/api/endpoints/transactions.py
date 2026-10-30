import csv
import io
from datetime import datetime, timezone
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from app.api.dependencies import get_current_user, get_database, _extract_user_id
from app.schemas.payment import (
    PaymentTransactionListResponse,
    PaymentTransactionDetailResponse,
)
from app.services.payin_service import PayinService
from app.services.pdf_service import PDFService

router = APIRouter()


@router.get("", response_model=PaymentTransactionListResponse)
@router.get("/", response_model=PaymentTransactionListResponse, include_in_schema=False)
async def list_transactions(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Records per page"),
    status: Optional[str] = Query(None, description="Status filter: PENDING, SUCCESS, FAILED, REFUNDED, CANCELLED, or ALL"),
    payment_mode: Optional[str] = Query(None, description="Payment mode filter: UPI, QR Code, Net Banking, Credit Card, Debit Card, or ALL"),
    search: Optional[str] = Query(None, description="Search by GROWG transaction ID, order ID, plan name, or gateway reference"),
    date_from: Optional[str] = Query(None, description="Filter transactions created on or after this date (ISO format or YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter transactions created on or before this date (ISO format or YYYY-MM-DD)"),
    start_date: Optional[str] = Query(None, description="Alias for date_from"),
    end_date: Optional[str] = Query(None, description="Alias for date_to"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns the authenticated user's transaction history sorted by latest transactions first.
    Supports pagination, multi-field search, status filtering, payment mode filtering, and date ranges.
    Guarantees user isolation: never exposes another user's transactions.
    """
    user_id = _extract_user_id(current_user)
    effective_date_from = date_from or start_date
    effective_date_to = date_to or end_date

    return await PayinService.get_user_transactions(
        db,
        user_id=user_id,
        page=page,
        limit=limit,
        status=status,
        payment_mode=payment_mode,
        search=search,
        date_from=effective_date_from,
        date_to=effective_date_to,
    )


@router.get("/export")
async def export_transactions_report(
    format: str = Query("csv", description="Export format: 'csv' or 'pdf'"),
    status: Optional[str] = Query(None, description="Status filter"),
    payment_mode: Optional[str] = Query(None, description="Payment mode filter"),
    search: Optional[str] = Query(None, description="Search query"),
    date_from: Optional[str] = Query(None, description="Start date"),
    date_to: Optional[str] = Query(None, description="End date"),
    start_date: Optional[str] = Query(None, description="Alias for date_from"),
    end_date: Optional[str] = Query(None, description="Alias for date_to"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Exports the authenticated user's transaction report as a downloadable CSV or PDF file.
    Applies search, status, payment mode, and date range filters.
    Strictly scoped to the authenticated user.
    """
    user_id = _extract_user_id(current_user)
    effective_date_from = date_from or start_date
    effective_date_to = date_to or end_date

    # Fetch up to 1000 matching records for the user
    res = await PayinService.get_user_transactions(
        db,
        user_id=user_id,
        page=1,
        limit=1000,
        status=status,
        payment_mode=payment_mode,
        search=search,
        date_from=effective_date_from,
        date_to=effective_date_to,
    )
    transactions = res.get("data", [])
    export_fmt = (format or "csv").strip().lower()
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # CSV Export
    if export_fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Transaction ID",
            "Order ID",
            "Created Date",
            "Completed Date",
            "Plan Name",
            "Billing Cycle",
            "Amount (INR)",
            "Base Amount (INR)",
            "GST Amount (INR)",
            "Payment Mode",
            "Payment Provider",
            "Gateway Reference",
            "Status",
            "AI Credits",
            "Failure / Notes"
        ])

        for tx in transactions:
            dt_created = tx.get("created_at")
            c_str = dt_created.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_created, datetime) else str(dt_created or "")
            dt_comp = tx.get("completed_at")
            comp_str = dt_comp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt_comp, datetime) else str(dt_comp or "")

            writer.writerow([
                tx.get("transaction_id", ""),
                tx.get("order_id", ""),
                c_str,
                comp_str,
                tx.get("plan_name", ""),
                tx.get("billing_cycle", ""),
                f"{float(tx.get('amount', 0.0)):.2f}",
                f"{float(tx.get('base_amount') or tx.get('amount', 0.0)):.2f}",
                f"{float(tx.get('gst_amount') or 0.0):.2f}",
                tx.get("payment_mode", "Unknown"),
                tx.get("payment_gateway", "Finunique Payin"),
                tx.get("gateway_transaction_id") or tx.get("provider_reference") or "",
                str(tx.get("status", "")).upper(),
                tx.get("credits_included", 0),
                tx.get("failure_reason") or ""
            ])

        csv_content = output.getvalue().encode("utf-8-sig")
        filename = f"transactions_report_{user_id[:8]}_{ts_str}.csv"
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "text/csv; charset=utf-8"
            }
        )

    # PDF Export
    elif export_fmt == "pdf":
        user_info = {
            "name": current_user.get("name") or current_user.get("full_name") or "User",
            "email": current_user.get("email") or "N/A",
            "phone": current_user.get("phone_number") or current_user.get("mobile") or "N/A"
        }
        filters = {
            "status": status or "All",
            "payment_mode": payment_mode or "All",
            "search": search or "None",
            "date_from": effective_date_from or "Earliest",
            "date_to": effective_date_to or "Latest"
        }
        pdf_bytes = PDFService.generate_transaction_list_pdf(transactions, user_info, filters)
        filename = f"transactions_report_{user_id[:8]}_{ts_str}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/pdf"
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format '{format}'. Supported formats: 'csv', 'pdf'."
        )


@router.get("/{transaction_id}", response_model=PaymentTransactionDetailResponse)
async def get_transaction_details(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Retrieves full details of a single transaction by GROWG transaction ID, internal order ID, or record ID.
    Strictly verifies ownership: returns 403 Forbidden if transaction belongs to another user.
    """
    user_id = _extract_user_id(current_user)
    tx = await PayinService.get_transaction_by_id(db, user_id=user_id, transaction_id_or_order_id=transaction_id)
    if tx:
        return {"success": True, "data": tx}

    # Check if transaction exists under a different user to return 403 Forbidden
    clean_id = (transaction_id or "").strip()
    from bson import ObjectId
    other_query = [
        {"transaction_id": clean_id},
        {"transaction_id": clean_id.upper()},
        {"order_id": clean_id},
        {"order_id": clean_id.upper()}
    ]
    if ObjectId.is_valid(clean_id):
        other_query.append({"_id": ObjectId(clean_id)})

    other_tx = await db["payment_transactions"].find_one({"$or": other_query})
    if other_tx and str(other_tx.get("user_id")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission to view this transaction."
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Transaction '{transaction_id}' not found."
    )


@router.get("/{transaction_id}/receipt")
async def download_transaction_receipt(
    transaction_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Generates and returns an official branded PDF receipt / tax invoice for a transaction.
    Validates authenticated user ownership.
    """
    user_id = _extract_user_id(current_user)
    tx = await PayinService.get_transaction_by_id(db, user_id=user_id, transaction_id_or_order_id=transaction_id)
    if not tx:
        # Check if exists under another user
        clean_id = (transaction_id or "").strip()
        from bson import ObjectId
        other_query = [
            {"transaction_id": clean_id},
            {"transaction_id": clean_id.upper()},
            {"order_id": clean_id},
            {"order_id": clean_id.upper()}
        ]
        if ObjectId.is_valid(clean_id):
            other_query.append({"_id": ObjectId(clean_id)})

        other_tx = await db["payment_transactions"].find_one({"$or": other_query})
        if other_tx and str(other_tx.get("user_id")) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to download this receipt."
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found."
        )

    # Populate user details from current_user if missing in transaction
    if not tx.get("user_name") or tx.get("user_name") == "Valued Customer":
        tx["user_name"] = current_user.get("name") or current_user.get("full_name") or "Valued Customer"
    if not tx.get("user_email") or tx.get("user_email") == "N/A":
        tx["user_email"] = current_user.get("email") or "N/A"
    if not tx.get("user_phone") or tx.get("user_phone") == "N/A":
        tx["user_phone"] = current_user.get("phone_number") or current_user.get("mobile") or "N/A"

    pdf_bytes = PDFService.generate_receipt_pdf(tx)
    pub_id = tx.get("transaction_id") or tx.get("order_id") or "receipt"
    filename = f"receipt_{pub_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf"
        }
    )
