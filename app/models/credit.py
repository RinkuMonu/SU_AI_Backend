from typing import Optional
from app.models.base import MongoBaseModel

class CreditTransaction(MongoBaseModel):
    user_id: str
    business_id: Optional[str] = None
    transaction_type: str  # "deduction", "addition", "refund"
    amount: int
    feature: str
    reference_id: Optional[str] = None
    balance_before: int
    balance_after: int


class CreditBalance(MongoBaseModel):
    user_id: str
    business_id: Optional[str] = None
    balance: int = 0
