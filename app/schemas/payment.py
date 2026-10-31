from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

class PaymentCreateRequest(BaseModel):
    plan_id: str
    billing_cycle: Optional[str] = "monthly"

class PaymentCreateResponse(BaseModel):
    success: bool
    order_id: str
    transaction_id: Optional[str] = None
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
    transaction_id: Optional[str] = None
    can_cancel: bool = True
    message: str
    current_status: Optional[str] = None

class PaymentCallbackResponse(BaseModel):
    success: bool
    status: str
    message: str
    order_id: Optional[str] = None
    transaction_id: Optional[str] = None

class PaymentStatusResponse(BaseModel):
    order_id: str
    transaction_id: Optional[str] = None
    status: str
    can_cancel: bool = True
    amount: float
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_percentage: Optional[float] = None
    gst_amount: Optional[float] = None
    total_payable: Optional[float] = None
    currency: Optional[str] = "INR"
    payment_mode: Optional[str] = "Unknown"
    payment_gateway: Optional[str] = "Finunique Payin"
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    provider_reference: Optional[str] = None
    created_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    message: Optional[str] = None

class PaymentVerifyRequest(BaseModel):
    order_id: str

class PaymentVerifyResponse(BaseModel):
    success: bool
    status: str
    order_id: str
    transaction_id: Optional[str] = None
    verified: bool
    message: str
    plan_id: Optional[str] = None
    amount: Optional[float] = None
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_percentage: Optional[float] = None
    gst_amount: Optional[float] = None
    total_payable: Optional[float] = None
    payment_mode: Optional[str] = "Unknown"
    provider_reference: Optional[str] = None

class PaymentTransactionItem(BaseModel):
    id: str
    transaction_id: Optional[str] = None  # GROWG001 format
    order_id: str
    provider_reference: Optional[str] = None
    gateway_transaction_id: Optional[str] = None
    external_transaction_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    plan_id: str
    plan_name: str
    plan_duration: Optional[str] = None
    billing_cycle: Optional[str] = "monthly"
    amount: float
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_percentage: Optional[float] = None
    gst_amount: Optional[float] = None
    total_payable: Optional[float] = None
    currency: str = "INR"
    payment_mode: Optional[str] = "Unknown"
    payment_gateway: Optional[str] = "Finunique Payin"
    payment_provider: Optional[str] = "finunique_payin"
    status: str
    failure_reason: Optional[str] = None
    refund_details: Optional[Dict[str, Any]] = None
    payment_url: Optional[str] = None
    upi_url: Optional[str] = None
    qr_code: Optional[str] = None
    credits_included: Optional[int] = 0
    purchased_credits: Optional[int] = 0
    credits_granted: Optional[int] = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class PaymentTransactionListResponse(BaseModel):
    success: bool = True
    total: int
    page: int
    limit: int
    total_pages: int
    data: List[PaymentTransactionItem]

class PaymentTransactionDetailResponse(BaseModel):
    success: bool = True
    data: PaymentTransactionItem

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


# ===========================================================================
# Cashfree Subscriptions & AutoPay (Recurring) Schemas
# ===========================================================================

class CashfreeSubscriptionCreateRequest(BaseModel):
    plan_id: str = Field(..., description="Plan ID e.g. STARTER, GROWTH, BUSINESS, INFLUENCER")
    billing_cycle: Optional[str] = Field("monthly", description="monthly, quarterly, or yearly")
    customer_phone: Optional[str] = Field(None, description="10-digit customer mobile number for SMS/mandate")
    return_url: Optional[str] = Field(None, description="Frontend redirect URL after mandate approval")

class CashfreeSubscriptionResponse(BaseModel):
    success: bool
    subscription_id: str
    order_id: Optional[str] = None
    cf_subscription_id: Optional[str] = None
    subscription_session_id: Optional[str] = None
    payment_url: Optional[str] = None
    status: str
    auth_amount: float
    recurring_amount: float
    amount: Optional[float] = None
    plan_id: str
    plan_name: Optional[str] = None
    billing_cycle: str
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_percentage: Optional[float] = None
    gst_amount: Optional[float] = None
    total_payable: Optional[float] = None
    currency: str = "INR"

class CashfreeSubscriptionStatusResponse(BaseModel):
    success: Optional[bool] = True
    subscription_id: str
    order_id: Optional[str] = None
    cf_subscription_id: Optional[str] = None
    status: str
    auth_amount: float
    recurring_amount: float
    amount: Optional[float] = None
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = None
    gst_percentage: Optional[float] = None
    gst_amount: Optional[float] = None
    total_payable: Optional[float] = None
    plan_id: str
    plan_name: Optional[str] = None
    billing_cycle: str
    customer_email: Optional[str] = None
    auth_status: Optional[str] = None
    next_schedule_date: Optional[str] = None
    verified: Optional[bool] = False
    message: Optional[str] = None

class CashfreeSubscriptionVerifyRequest(BaseModel):
    subscription_id: Optional[str] = None
    order_id: Optional[str] = None

class WebhookResponse(BaseModel):
    success: bool
    message: str
