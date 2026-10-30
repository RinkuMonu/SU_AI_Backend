from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class CashfreeSubscriptionCreateRequest(BaseModel):
    plan_id: str = Field(..., description="Plan ID e.g. STARTER, GROWTH, BUSINESS, INFLUENCER")
    billing_cycle: Optional[str] = Field("monthly", description="monthly, quarterly, or yearly")
    customer_phone: Optional[str] = Field(None, description="10-digit customer mobile number for SMS/mandate")
    return_url: Optional[str] = Field(None, description="Frontend redirect URL after mandate approval")

class CashfreeSubscriptionResponse(BaseModel):
    success: bool
    subscription_id: str
    cf_subscription_id: Optional[str] = None
    subscription_session_id: Optional[str] = None
    payment_url: Optional[str] = None
    status: str
    auth_amount: float
    recurring_amount: float
    plan_id: str
    billing_cycle: str
    currency: str = "INR"

class CashfreeSubscriptionStatusResponse(BaseModel):
    subscription_id: str
    cf_subscription_id: Optional[str] = None
    status: str
    auth_amount: float
    recurring_amount: float
    plan_id: str
    billing_cycle: str
    customer_email: Optional[str] = None
    auth_status: Optional[str] = None
    next_schedule_date: Optional[str] = None

class WebhookResponse(BaseModel):
    success: bool
    message: str
