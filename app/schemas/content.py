from pydantic import BaseModel, Field
from typing import Optional, List


class GeneratePostRequest(BaseModel):
    product_id: str
    product_ids: Optional[List[str]] = None
    platform: str = Field(
        default="instagram",
        description="Target social platform"
    )
    objective: str = Field(
        default="product_promotion",
        description="Marketing objective"
    )
    language: str = "English"
    additional_instruction: Optional[str] = None


class GeneratedPost(BaseModel):
    product_id: str
    platform: str
    objective: str

    headline: str
    caption: str
    call_to_action: str

    hashtags: List[str]

    creative_direction: Optional[str] = None