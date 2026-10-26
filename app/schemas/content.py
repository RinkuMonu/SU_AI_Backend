from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ProductDetail(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    features: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)


class GenerateContentRequest(BaseModel):
    # Product identification (lookup by ID from database)
    product_id: Optional[str] = ""
    product_ids: Optional[List[str]] = Field(default_factory=list)

    # Direct product details (if not looking up from DB or augmenting/overriding)
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    sale_price: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    features: Optional[List[str]] = Field(default_factory=list)
    product_images: Optional[List[str]] = Field(default_factory=list)
    product_details: Optional[Dict[str, Any]] = None

    # Content generation parameters
    content_type: str = Field(
        default="post",
        description="Type of content: 'post' (or 'social_post'), 'caption', 'ad' (or 'advertisement'), 'reel'"
    )
    platform: str = Field(
        default="instagram",
        description="Target social platform (instagram, facebook, linkedin, twitter, etc.)"
    )
    objective: str = Field(
        default="product_promotion",
        description="Marketing objective (product_promotion, sale, brand_awareness, lead_generation, etc.)"
    )
    language: str = "English"
    additional_instruction: Optional[str] = None
    reference_images: Optional[List[str]] = Field(default_factory=list)

    # Brand Kit integration
    use_brand_kit: bool = Field(
        default=False,
        description="Whether to use the authenticated user's saved Brand Kit"
    )

    # Manual branding settings (applied when use_brand_kit=False)
    brand_name: Optional[str] = None
    brand_voice: Optional[str] = None
    brand_colors: Optional[List[str]] = None
    target_audience: Optional[str] = None
    tone: Optional[str] = None
    cta: Optional[str] = None


class GeneratePostRequest(GenerateContentRequest):
    """Backward-compatible alias for GenerateContentRequest."""
    pass


class GeneratedContentResponse(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    content_type: str = "post"
    product_id: Optional[str] = ""
    product_ids: Optional[List[str]] = Field(default_factory=list)
    product_details: Optional[Dict[str, Any]] = None
    platform: str = "instagram"
    objective: str = "product_promotion"

    headline: str
    caption: str
    call_to_action: str

    hashtags: List[str] = Field(default_factory=list)

    # Ad-specific fields
    primary_text: Optional[str] = None
    description: Optional[str] = None

    creative_direction: Optional[str] = None
    image_url: Optional[str] = None
    media_url: Optional[str] = None
    use_brand_kit: bool = False
    brand_kit_applied: bool = False
    brand_details: Optional[dict] = None

    model_config = {"populate_by_name": True}


class GeneratedPost(GeneratedContentResponse):
    """Backward-compatible alias for GeneratedContentResponse."""
    pass