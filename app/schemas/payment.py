from pydantic import BaseModel
from typing import Optional

class PaymentCreateRequest(BaseModel):
    plan_id: str

class PaymentCreateResponse(BaseModel):
    success: bool
    order_id: str
    payment_url: str
    status: str

class PaymentCallbackResponse(BaseModel):
    success: bool
    status: str
    message: str

class PaymentStatusResponse(BaseModel):
    order_id: str
    status: str
    amount: int
