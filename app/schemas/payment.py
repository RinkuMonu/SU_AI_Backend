from pydantic import BaseModel
from typing import Optional

class PaymentCreateRequest(BaseModel):
    plan_id: str
    billing_cycle: Optional[str] = "monthly"

class PaymentCreateResponse(BaseModel):
    success: bool
    order_id: str
    payment_url: str
    status: str
    billing_cycle: Optional[str] = "monthly"

class PaymentCallbackResponse(BaseModel):
    success: bool
    status: str
    message: str

class PaymentStatusResponse(BaseModel):
    order_id: str
    status: str
    amount: float
    base_amount: Optional[float] = None
    gst_amount: Optional[float] = None

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

