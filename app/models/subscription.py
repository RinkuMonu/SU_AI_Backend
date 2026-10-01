from typing import Optional
from datetime import datetime
from app.models.base import MongoBaseModel

class Subscription(MongoBaseModel):
    user_id: str
    plan_id: str
    status: str = "active"  # active, canceled, past_due, expired
    payment_provider: Optional[str] = None
    payment_id: Optional[str] = None
    subscription_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    auto_renew: bool = True
