from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from app.models.base import PyObjectId

class ReviewCreate(BaseModel):
    customer_name: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=10)
    review_text: str = Field(..., min_length=1)
    status: str = "New"

class ReviewUpdate(BaseModel):
    status: Optional[str] = None
    reply: Optional[str] = None

class ReviewResponse(BaseModel):
    id: PyObjectId
    business_id: str
    customer_name: str
    rating: int
    review_text: str
    status: str
    reply: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
