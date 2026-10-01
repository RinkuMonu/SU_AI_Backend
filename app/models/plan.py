from typing import List, Optional
from pydantic import Field
from app.models.base import MongoBaseModel

class Plan(MongoBaseModel):
    plan_id: str
    name: str
    price: int
    currency: str = "INR"
    billing_cycle: str = "monthly"
    credits: int
    post_limit: int = -1  # -1 for unlimited
    reel_limit: int = -1
    team_members: int = 1
    features: List[str] = Field(default_factory=list)
    watermark: bool = False
    multiple_businesses: bool = False
    api_access: bool = False
    white_label: bool = False
