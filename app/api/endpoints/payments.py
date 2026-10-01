from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Any, Dict
from app.api.dependencies import get_current_user, get_database
from app.schemas.payment import PaymentCreateRequest, PaymentCreateResponse, PaymentCallbackResponse, PaymentStatusResponse
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
    result = await PayinService.create_payment(db, user_id, user_email, request.plan_id)
    return result

@router.post("/payin/callback", response_model=PaymentCallbackResponse)
async def payment_callback(
    request: Request,
    db: Database = Depends(get_database)
):
    # Payin might send application/json or form-data
    if request.headers.get("content-type") == "application/json":
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)
        
    headers = dict(request.headers)
    result = await PayinService.process_callback(db, payload, headers)
    return result

@router.get("/payin/status/{order_id}", response_model=PaymentStatusResponse)
async def payment_status(
    order_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_database)
):
    transaction = await db["payment_transactions"].find_one({"order_id": order_id})
    if not transaction:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if transaction["user_id"] != str(current_user["id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return {
        "order_id": order_id,
        "status": transaction["status"],
        "amount": transaction["amount"]
    }
