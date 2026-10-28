from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class PlanPricingDetail(BaseModel):
    price: float
    formatted_price: str
    period_label: str
    duration_days: int


class PlanCard(BaseModel):
    id: str
    name: str
    plan_tier: str
    price: float
    currency: str = "INR"
    display_price: str
    period_label: str
    credits: int
    credits_badge: str
    description: str
    post_limit: int
    reel_limit: int
    highlights: List[str] = []
    features: List[str] = []
    billing_cycles: Dict[str, Any] = {}
    is_current: bool = False


class ActivePlanSummary(BaseModel):
    plan_id: str
    plan_name: str
    billing_cycle: str
    credits_remaining: int
    credits_total: int
    status: str
    is_paid_plan: bool
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PlanOnboardingStatusResponse(BaseModel):
    role: Optional[str] = None
    brand_kit_completed: bool
    social_connectivity_completed: bool
    plan_activation_completed: bool
    plan_activation_completed_at: Optional[datetime] = None
    is_eligible: bool
    should_show_modal: bool
    requires_plan_selection: bool = False
    is_plan_required: bool = False
    subscription_status: Optional[str] = "inactive"
    current_plan: Optional[str] = None
    is_paid_plan: bool = False
    active_plan: Optional[ActivePlanSummary] = None
    available_plans: List[PlanCard] = []
    billing_cycles: List[str] = ["monthly", "quarterly", "yearly"]
    currency: str = "INR"

