from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SourceImageItem(BaseModel):
    id: str = Field(..., description="Stable unique identifier for the source image")
    url: str = Field(..., description="Public HTTP/HTTPS or media path for the image")
    source: str = Field(..., description="website | google_maps | brand_kit | marketplace | b2b | product | upload")
    thumbnail_url: Optional[str] = Field(None, description="Optional thumbnail version")
    caption: Optional[str] = Field(None, description="Optional description or title of the image")
    is_logo: bool = Field(False, description="True if this asset is a verified brand logo")
    width: Optional[int] = None
    height: Optional[int] = None


class FirstPostSourceImagesResponse(BaseModel):
    success: bool = True
    business_id: str
    online_presence: Optional[str] = None
    images: List[SourceImageItem] = Field(default_factory=list)
    total_count: int = 0


class FirstPostImageUploadResponse(BaseModel):
    success: bool = True
    image_url: str
    image_id: str
    filename: str
    source: str = "upload"
    content_type: str
    size_bytes: int


class FirstPostGenerateRequest(BaseModel):
    content_choice: Optional[str] = Field(
        "post_maker",
        description="Selected first content experience: 'post_maker', 'ai_photoshoot', or 'reel_maker'"
    )
    selected_image_url: Optional[str] = Field(
        None,
        description="URL of existing source image or uploaded photo to base generation on"
    )
    prompt: Optional[str] = Field(
        None,
        description="Custom instruction or topic for first-post copy"
    )
    additional_instruction: Optional[str] = Field(
        None,
        description="Alias for prompt"
    )
    platform: Optional[str] = Field(
        "instagram",
        description="Target social platform (instagram, facebook, linkedin, twitter)"
    )
    objective: Optional[str] = Field(
        "product_promotion",
        description="Marketing objective (product_promotion, brand_awareness, festive_greeting)"
    )
    language: Optional[str] = Field(
        "English",
        description="Content language"
    )
    idempotency_key: Optional[str] = Field(
        None,
        description="Optional client idempotency key to prevent double clicks and duplicate jobs"
    )
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    category: Optional[str] = None


class FirstPostPreviewItem(BaseModel):
    id: str = Field(..., description="Unique preview identifier (e.g. preview_1, preview_2, preview_3)")
    variation_index: int = Field(..., description="0, 1, or 2")
    title: str = Field(..., description="Short title describing the creative angle")
    headline: Optional[str] = Field(None, description="Hook or banner headline")
    caption: str = Field(..., description="Full post caption or redacted copy if locked")
    hashtags: List[str] = Field(default_factory=list, description="Target hashtags")
    call_to_action: Optional[str] = None
    image_url: Optional[str] = None
    media_url: Optional[str] = None
    creative_direction: Optional[str] = None
    content_type: str = "post"
    content_id: Optional[str] = Field(
        None,
        description="MongoDB _id in 'contents' collection for direct loading in the Create Post editor"
    )
    is_locked: bool = Field(
        False,
        description="True if preview is locked behind paid subscription"
    )
    lock_reason: Optional[str] = Field(
        None,
        description="Reason preview is locked (e.g. 'upgrade_required')"
    )
    upgrade_required: bool = Field(
        False,
        description="True if upgrading to a paid plan unlocks this preview"
    )


class FirstPostJobResponse(BaseModel):
    success: bool = True
    job_id: str
    status: str = Field(..., description="pending | processing | completed | failed")
    progress: int = Field(0, description="Real execution progress: 0 to 100")
    content_choice: str = "post_maker"
    previews: List[FirstPostPreviewItem] = Field(default_factory=list)
    unlocked_preview_id: Optional[str] = None
    unlocked_content_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FirstContentChoiceRequest(BaseModel):
    content_choice: str = Field(
        ...,
        description="'post_maker' | 'ai_photoshoot' | 'reel_maker'"
    )


class FirstContentChoiceResponse(BaseModel):
    success: bool = True
    content_choice: str
    next_action: str
    route: str
