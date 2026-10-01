from datetime import datetime, timezone
from typing import Optional
from app.models.base import MongoBaseModel

class PaymentTransaction(MongoBaseModel):
    user_id: str
    plan_id: str
    plan_name: str
    amount: int
    currency: str = "INR"
    order_id: str
    external_transaction_id: Optional[str] = None
    status: str = "pending"  # pending, initiated, success, failed, cancelled, verification_failed
    payment_url: Optional[str] = None
    verified_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
