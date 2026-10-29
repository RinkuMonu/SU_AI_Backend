from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

class PaymentCreateRequest(BaseModel):
    plan_id: str
    billing_cycle: Optional[str] = "monthly"

class PaymentCreateResponse(BaseModel):
    success: bool
    order_id: str
    payment_url: str
    upi_url: Optional[str] = None
    qr_code: Optional[str] = None
    provider_reference: Optional[str] = None
    amount: Optional[float] = None
    plan_name: Optional[str] = None
    status: str
    billing_cycle: Optional[str] = "monthly"
    currency: Optional[str] = "INR"

class PaymentCancelRequest(BaseModel):
    order_id: str
    reason: Optional[str] = "User cancelled payment"

class PaymentCancelResponse(BaseModel):
    success: bool
    status: str
    order_id: str
    can_cancel: bool = True
    message: str
    current_status: Optional[str] = None

class PaymentCallbackResponse(BaseModel):
    success: bool
    status: str
    message: str
    order_id: Optional[str] = None

class PaymentStatusResponse(BaseModel):
    order_id: str
    status: str
    can_cancel: bool = True
    amount: float
    base_amount: Optional[float] = None
    gst_amount: Optional[float] = None
    currency: Optional[str] = "INR"
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    provider_reference: Optional[str] = None
    created_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    message: Optional[str] = None

class PaymentVerifyRequest(BaseModel):
    order_id: str

class PaymentVerifyResponse(BaseModel):
    success: bool
    status: str
    order_id: str
    verified: bool
    message: str
    plan_id: Optional[str] = None
    amount: Optional[float] = None
    provider_reference: Optional[str] = None

class PaymentTransactionItem(BaseModel):
    id: str
    order_id: str
    provider_reference: Optional[str] = None
    external_transaction_id: Optional[str] = None
    plan_id: str
    plan_name: str
    amount: float
    base_amount: Optional[float] = None
    gst_amount: Optional[float] = None
    currency: str = "INR"
    billing_cycle: Optional[str] = "monthly"
    status: str
    failure_reason: Optional[str] = None
    payment_url: Optional[str] = None
    purchased_credits: Optional[int] = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

class PaymentTransactionListResponse(BaseModel):
    success: bool = True
    total: int
    page: int
    limit: int
    total_pages: int
    data: List[PaymentTransactionItem]

class TestPlanResetRequest(BaseModel):
    target_user_id: Optional[str] = None
    confirm: Optional[bool] = True

class TestPlanResetResponse(BaseModel):
    success: bool
    message: str
    user_id: str
    previous_plan: str
    current_plan: str
    new_plan: Optional[str] = "FREE"
    credits_remaining: int
    credits_available: Optional[int] = 5
    audit_preserved_transactions: List[str] = []
    preserved_paid_orders: Optional[List[str]] = []
    cancelled_pending_orders: Optional[List[str]] = []
