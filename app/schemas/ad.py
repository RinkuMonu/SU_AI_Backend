from pydantic import BaseModel
from typing import Optional, Literal

class AdRequest(BaseModel):
    product_id: Optional[str] = None
    content_id: Optional[str] = None
    prompt: Optional[str] = None
    platform: Optional[str] = None
    objective: Optional[str] = None
    language: str = "English"
    target_audience: Optional[str] = None
    additional_instruction: Optional[str] = None
    cta: Optional[str] = "Shop Now"

class AdResponse(BaseModel):
    success: bool
    message: str
    data: dict
