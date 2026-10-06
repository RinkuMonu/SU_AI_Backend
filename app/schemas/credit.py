from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    plan: str
    credits_total: int
    credits_remaining: int
    status: str
    created_at: datetime
    updated_at: datetime

class CreditBalanceResponse(BaseModel):
    plan: str
    credits_total: int
    credits_remaining: int
    credits_used: int

class CreditTransactionResponse(BaseModel):
    id: str
    transaction_type: str
    feature: Optional[str] = None
    amount: int
    balance_before: int
    balance_after: int
    created_at: datetime

class CreditHistoryResponse(BaseModel):
    transactions: List[CreditTransactionResponse]
