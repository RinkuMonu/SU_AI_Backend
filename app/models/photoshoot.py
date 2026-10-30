import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel, PyObjectId


class ProductImageAsset(BaseModel):
    """Metadata for uploaded, enhanced, or generated product images."""
    image_id: str = Field(default_factory=lambda: f"img_{uuid.uuid4().hex[:12]}")
    session_id: str
    user_id: str
    url: str
    filename: str
    angle: str = "Front"  # Front, Back, Side, Close-up, Other
    file_size: int = 0
    dimensions: Dict[str, int] = Field(default_factory=lambda: {"width": 1024, "height": 1024})
    content_type: str = "image/jpeg"
    image_type: str = "original"  # original, enhanced, generated
    enhancement_style: Optional[str] = None  # Studio Premium, Luxury Cinematic, Marketplace White
    is_selected: bool = False
    is_saved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIModelProfile(BaseModel):
    """Curated AI human model profile for model-based fashion and product photoshoot."""
    model_id: str
    name: str
    gender: str  # male, female, unisex
    ethnicity: str  # Indian / South Asian, East Asian, Caucasian, Multicultural
    thumbnail_url: str
    preview_url: str
    supported_categories: List[str] = Field(default_factory=list)
    description: str = ""
    is_active: bool = True


class ProductPhotoshootSession(MongoBaseModel):
    """
    Unified AI Product Photoshoot Studio Session.
    Supports both model-based and product-only workflows through a single session entity.
    """
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    user_id: str
    title: Optional[str] = "Untitled Photoshoot"
    product_category: Optional[str] = None
    product_type: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None
    original_images: List[Dict[str, Any]] = Field(default_factory=list)
    enhanced_images: List[Dict[str, Any]] = Field(default_factory=list)
    selected_enhanced_image_ids: List[str] = Field(default_factory=list)
    use_model: bool = False
    model_id: Optional[str] = None
    model_details: Optional[Dict[str, Any]] = None
    selected_styles: List[str] = Field(default_factory=list)
    custom_prompt: Optional[str] = None
    prepared_prompt: Optional[str] = None
    status: str = "created"  # created, uploaded, analyzed, enhanced, prompt_ready, generating, completed, failed
    generation_jobs: List[str] = Field(default_factory=list)
    generated_images: List[Dict[str, Any]] = Field(default_factory=list)
    saved_image_ids: List[str] = Field(default_factory=list)


class PhotoshootGenerationJob(MongoBaseModel):
    """Asynchronous background generation job for photoshoot batches."""
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")
    session_id: str
    user_id: str
    status: str = "pending"  # pending, processing, completed, failed
    progress_percent: int = 0
    total_images: int = 5
    completed_images: int = 0
    use_model: bool = False
    model_id: Optional[str] = None
    styles: List[str] = Field(default_factory=list)
    prompt_used: str = ""
    result_images: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    credits_deducted: int = 5
    completed_at: Optional[datetime] = None


# Legacy helper maintained for backward compatibility
class PhotoshootModel:
    @staticmethod
    def create_document(
        user_id: str,
        product_id: str,
        style: str,
        background: str,
        model: Optional[str],
        pose: Optional[str],
        generated_image: str,
    ):
        return {
            "user_id": user_id,
            "product_id": product_id,
            "type": "photoshoot",
            "style": style,
            "background": background,
            "model": model,
            "pose": pose,
            "generated_image": generated_image,
            "status": "generated",
            "created_at": datetime.now(timezone.utc),
        }
