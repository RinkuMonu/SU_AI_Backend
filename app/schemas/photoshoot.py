from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Phase 1: Upload Schemas
# ---------------------------------------------------------------------------

class UploadedImageItem(BaseModel):
    image_id: str
    url: str
    filename: str
    angle: str = "Front"
    file_size: int
    dimensions: Dict[str, int]
    content_type: str


class ProductUploadResponse(BaseModel):
    success: bool = True
    session_id: str
    workflow_mode: Optional[str] = None
    product_category: Optional[str] = None
    total_uploaded: int
    uploaded_images: List[UploadedImageItem]
    message: str = "Product images uploaded and session initialized successfully."


# ---------------------------------------------------------------------------
# Phase 2: Analysis Schemas
# ---------------------------------------------------------------------------

class ProductAnalysisRequest(BaseModel):
    session_id: str
    image_ids: Optional[List[str]] = None


class ProductAnalysisData(BaseModel):
    product_category: str
    product_type: str
    main_colors: List[str] = Field(default_factory=list)
    shape_and_design: List[str] = Field(default_factory=list)
    material_and_texture: str = "Unspecified"
    brand_logo_and_text: Optional[str] = "None detected"
    product_details: List[str] = Field(default_factory=list)
    suitable_for_model: bool = False
    recommended_model_type: Optional[str] = None  # male, female, unisex, none
    recommended_styles: List[str] = Field(default_factory=list)
    confidence_notes: Optional[str] = None


class ProductAnalysisResponse(BaseModel):
    success: bool = True
    session_id: str
    analysis: ProductAnalysisData
    message: str = "AI product visual analysis completed successfully."


# ---------------------------------------------------------------------------
# Phase 3: Enhancement Schemas
# ---------------------------------------------------------------------------

class ProductEnhanceRequest(BaseModel):
    session_id: str
    image_id: Optional[str] = None
    styles: Optional[List[str]] = Field(
        default_factory=lambda: ["Studio Premium", "Luxury Cinematic", "Marketplace White"]
    )


class EnhancedImageItem(BaseModel):
    image_id: str
    source_image_id: str
    style: str
    url: str
    is_selected: bool = False
    created_at: datetime


class ProductEnhanceResponse(BaseModel):
    success: bool = True
    session_id: str
    total_variations: int
    enhanced_images: List[EnhancedImageItem]
    message: str = "Product image enhancement variations generated."


class SelectEnhancedRequest(BaseModel):
    selected_image_ids: List[str]


# ---------------------------------------------------------------------------
# Phase 4: Model Selection Schemas
# ---------------------------------------------------------------------------

class AIModelItem(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_id: str
    name: str
    gender: str
    ethnicity: str
    thumbnail_url: str
    preview_url: str
    supported_categories: List[str]
    description: str = ""
    identity_prompt: Optional[str] = None


class AIModelListResponse(BaseModel):
    success: bool = True
    total: int
    models: List[AIModelItem]


# ---------------------------------------------------------------------------
# Phase 5: Photography Styles Schemas
# ---------------------------------------------------------------------------

class PhotographyStyleItem(BaseModel):
    id: str
    name: str
    description: str
    category_fit: List[str]
    requires_model: bool = False
    pose: Optional[str] = None
    lighting: str
    preview_url: Optional[str] = None


class PhotographyStylesResponse(BaseModel):
    success: bool = True
    category: str
    use_model: bool
    workflow_mode: Optional[str] = None
    styles: List[PhotographyStyleItem]


# ---------------------------------------------------------------------------
# Phase 6: Prepare Prompt Schemas
# ---------------------------------------------------------------------------

class PreparePromptRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    workflow_mode: Optional[str] = None
    custom_prompt: Optional[str] = None
    language: Optional[str] = "en"
    use_model: Optional[bool] = False
    model_id: Optional[str] = None
    selected_styles: Optional[List[str]] = Field(default_factory=list)


class PreparePromptResponse(BaseModel):
    success: bool = True
    session_id: str
    workflow_mode: Optional[str] = None
    prepared_prompt: str
    detected_language: Optional[str] = "en"
    workflow_summary: Dict[str, Any]
    message: str = "Multilingual instructions interpreted and synthesized into studio photographic specifications."


# ---------------------------------------------------------------------------
# Phase 7: Photoshoot Generation Schemas
# ---------------------------------------------------------------------------

class PhotoshootGenerateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str
    workflow_mode: Optional[str] = None
    selected_enhanced_image_ids: Optional[List[str]] = None
    product_category: Optional[str] = None
    use_model: bool = False
    model_id: Optional[str] = None
    selected_styles: List[str] = Field(default_factory=list)
    custom_prompt: Optional[str] = None
    image_count: int = Field(default=5, ge=1, le=10)


class PhotoshootGenerateResponse(BaseModel):
    success: bool = True
    session_id: str
    workflow_mode: Optional[str] = None
    job_id: str
    status: str = "pending"
    estimated_time_seconds: int = 15
    message: str = "Photoshoot generation started. Poll status endpoint for progress."


class GeneratedImageItem(BaseModel):
    image_id: str
    session_id: str
    style_applied: str
    url: str
    is_saved: bool = False
    created_at: datetime


class PhotoshootJobStatusResponse(BaseModel):
    success: bool = True
    job_id: str
    session_id: str
    workflow_mode: Optional[str] = None
    status: str  # pending, processing, completed, partial, failed
    progress_percent: int
    completed_images: int
    total_images: int
    failed_images: int = 0
    failed_items: List[Dict[str, Any]] = Field(default_factory=list)
    can_retry: bool = False
    result_images: List[GeneratedImageItem] = Field(default_factory=list)
    error: Optional[str] = None


class RetryJobResponse(BaseModel):
    success: bool = True
    job_id: str
    session_id: str
    status: str
    retrying_count: int
    message: str


class PhotoshootResultsResponse(BaseModel):
    success: bool = True
    session_id: str
    workflow_mode: Optional[str] = None
    status: str
    total_images: int
    use_model: bool
    results: List[GeneratedImageItem]


# ---------------------------------------------------------------------------
# Phase 8: Gallery & Downloads Schemas
# ---------------------------------------------------------------------------

class SaveImagesRequest(BaseModel):
    image_ids: List[str]


class SaveImagesResponse(BaseModel):
    success: bool = True
    session_id: str
    saved_count: int
    saved_image_ids: List[str]
    message: str = "Selected images saved to your permanent gallery."


class RegenerateImageRequest(BaseModel):
    style: Optional[str] = None
    custom_prompt: Optional[str] = None


class GallerySessionItem(BaseModel):
    session_id: str
    title: str
    workflow_mode: Optional[str] = None
    product_category: Optional[str] = "Product"
    product_type: Optional[str] = "Item"
    use_model: bool = False
    thumbnail_url: Optional[str] = None
    total_generated: int = 0
    saved_count: int = 0
    created_at: datetime


class GalleryResponse(BaseModel):
    success: bool = True
    total: int
    page: int
    limit: int
    sessions: List[GallerySessionItem]

