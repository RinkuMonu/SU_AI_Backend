from pydantic import BaseModel, Field
from typing import Optional, List


class GeneratePostRequest(BaseModel):
    product_id: Optional[str] = ""
    product_ids: Optional[List[str]] = []
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
    reference_images: Optional[List[str]] = []


class GeneratedPost(BaseModel):
    product_id: Optional[str] = ""
    platform: str = "instagram"
    objective: str = "product_promotion"

    headline: str
    caption: str
    call_to_action: str

    hashtags: List[str] = []

    creative_direction: Optional[str] = None
    image_url: Optional[str] = None
    media_url: Optional[str] = None