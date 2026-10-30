from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.models.base import MongoBaseModel

class PaymentTransaction(MongoBaseModel):
    user_id: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_phone: Optional[str] = None
    plan_id: str
    plan_name: str
    plan_duration: Optional[str] = "monthly"
    billing_cycle: Optional[str] = "monthly"
    amount: float
    base_amount: Optional[float] = None
    gst_rate: Optional[float] = 0.0
    gst_amount: Optional[float] = 0.0
    currency: str = "INR"
    order_id: str
    transaction_id: Optional[str] = None  # GROWG001 format
    payment_mode: Optional[str] = "Unknown"
    payment_gateway: Optional[str] = "Finunique Payin"
    payment_provider: Optional[str] = "finunique_payin"
    gateway_transaction_id: Optional[str] = None
    provider_reference: Optional[str] = None
    external_transaction_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, SUCCESS, FAILED, REFUNDED, CANCELLED
    payment_url: Optional[str] = None
    upi_url: Optional[str] = None
    qr_code: Optional[str] = None
    purchased_credits: Optional[int] = 0
    credits_included: Optional[int] = 0
    credits_granted: Optional[int] = 0
    verified_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    refund_details: Optional[Dict[str, Any]] = None
