"""
Fashion AI Schemas
Pydantic request/response models for the Fashion AI module.
"""
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ----------------------------------------------
# Enums / Literals
# ----------------------------------------------

FashionCategory = Literal["tshirt", "shirt", "dress", "hoodie", "jacket", "top", "other"]
GenderType = Literal["male", "female", "unisex"]
ModelType = Literal["male", "female"]
PoseType = Literal["standing", "walking", "sitting", "hands_in_pockets", "crossed_arms", "looking_left", "looking_right", "custom"]
BackgroundType = Literal["studio", "street", "cafe", "office", "home", "beach", "luxury_store", "gym", "outdoor", "custom"]
ShotType = Literal["full_body", "upper_body", "close_up"]
ViewType = Literal["front", "back", "side"]
GenerationStatus = Literal["pending", "processing", "completed", "failed"]


# ----------------------------------------------
# Fashion Product Schemas
# ----------------------------------------------

class FashionProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: FashionCategory
    gender: GenderType
    color: str = Field(..., min_length=1, max_length=100)
    image_url: str
    description: Optional[str] = Field(None, max_length=1000)


class FashionProductResponse(BaseModel):
    id: str
    user_id: str
    name: str
    category: str
    gender: str
    color: str
    image_url: str
    processed_image_url: Optional[str] = None
    background_removed: bool = False
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ----------------------------------------------
# AI Photoshoot Schemas
# ----------------------------------------------

MALE_STYLES = ["casual", "streetwear", "luxury", "fitness"]
FEMALE_STYLES = ["casual", "fashion", "streetwear", "luxury"]


class PhotoshootGenerateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    product_id: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    garment_name: Optional[str] = None
    model_type: ModelType
    model_style: str
    pose: PoseType
    background: BackgroundType
    location: Optional[str] = None
    shot_type: ShotType
    view: ViewType
    custom_pose_description: Optional[str] = Field(None, max_length=300)
    custom_background_description: Optional[str] = Field(None, max_length=300)


class PhotoshootGenerateResponse(BaseModel):
    success: bool
    generation_id: str
    status: GenerationStatus
    message: str = "Fashion photoshoot generation started"


class GenerationStatusResponse(BaseModel):
    success: bool
    generation_id: str
    status: GenerationStatus
    images: Optional[List[str]] = None
    prompt_used: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ----------------------------------------------
# Virtual Try-On Schemas
# ----------------------------------------------

class VirtualTryOnRequest(BaseModel):
    person_image_url: str
    product_id: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    garment_name: Optional[str] = None


class VirtualTryOnResponse(BaseModel):
    success: bool
    generation_id: str
    status: GenerationStatus
    message: str = "Virtual try-on started"


class TryOnStatusResponse(BaseModel):
    success: bool
    generation_id: str
    status: GenerationStatus
    result_image_url: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None


# ----------------------------------------------
# History Schemas
# ----------------------------------------------

class GenerationHistoryItem(BaseModel):
    model_config = {"protected_namespaces": ()}

    id: str
    type: str
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    model_type: Optional[str] = None
    model_style: Optional[str] = None
    pose: Optional[str] = None
    background: Optional[str] = None
    location: Optional[str] = None
    status: str
    result_images: Optional[List[str]] = None
    result_image_url: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GenerationHistoryResponse(BaseModel):
    success: bool
    data: List[GenerationHistoryItem]
    total: int


class ImageUploadResponse(BaseModel):
    success: bool
    image_url: str
    message: str = "Image uploaded successfully"
