from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class CaptionRequest(BaseModel):
    product_id: str
    objective: str
    tone: str
    language: str
    offer: str
    cta: str

class CaptionResponse(BaseModel):
    caption: str
    hashtags: List[str]
    cta: str

class AIGenerationHistoryResponse(BaseModel):
    id: str
    user_id: str
    business_id: str
    generation_type: str
    provider: str
    model_name: str
    input_params: Dict[str, Any]
    output_data: Dict[str, Any]
    status: str
    execution_time_ms: int
    created_at: str

class ImageGenerationRequest(BaseModel):
    prompt: str
    product_id: Optional[str] = None
    reference_images: Optional[List[str]] = None
    additional_instruction: Optional[str] = None
