from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class GenerateReelRequest(BaseModel):
    product_id: str = "general"
    product_name: Optional[str] = None
    product_category: Optional[str] = None
    product_description: Optional[str] = None
    product_image_url: Optional[str] = None
    objective: str = "sale"
    platform: str = "instagram"
    language: str = "Hinglish"
    duration: int = 15  # seconds
    tone: Optional[str] = "energetic"
    offer: Optional[str] = None
    additional_instruction: Optional[str] = None
    generation_mode: Optional[str] = "product"  # "product" (default) or "creative"
    festival_theme: Optional[str] = "none"  # "none", "diwali", "holi", "eid", "christmas", "new_year"

    @validator("duration")
    def validate_duration(cls, v):
        allowed_durations = [10, 15, 20, 30]
        if v not in allowed_durations:
            raise ValueError(f"Duration must be one of {allowed_durations}")
        return v
        
    @validator("language")
    def validate_language(cls, v):
        allowed_languages = ["English", "Hindi", "Hinglish"]
        if v not in allowed_languages:
            raise ValueError(f"Language must be one of {allowed_languages}")
        return v

class ReelScene(BaseModel):
    scene_number: int = 1
    duration_seconds: int = 5
    visual: str = ""
    voiceover: str = ""
    on_screen_text: Optional[str] = ""
    transition: Optional[str] = "fade"
    camera_movement: Optional[str] = "slow push-in"
    lighting_environment: Optional[str] = "cinematic studio lighting"
    product_interaction: Optional[str] = "product showcased in authentic setting"
    main_subject: Optional[str] = None
    product_identity: Optional[str] = None
    veo_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None

class ReelScript(BaseModel):
    title: str = "AI Generated Reel"
    objective: Optional[str] = "Engage audience"
    advertising_objective: Optional[str] = None
    visual_concept: Optional[str] = None
    style_direction: Optional[str] = None
    target_audience: Optional[str] = None
    primary_product: Optional[str] = None
    product_category: Optional[str] = None
    generation_mode: Optional[str] = "product"
    festival_theme: Optional[str] = None
    veo_video_prompt: Optional[str] = None
    negative_constraints: Optional[str] = None
    hook: Optional[str] = ""
    hook_headline: Optional[str] = None
    hook_highlight: Optional[str] = None
    trending_audio: Optional[str] = "Trending Sound • Viral Hit"
    creator_name: Optional[str] = None
    follower_count: Optional[str] = "24.8K followers"
    likes_count: Optional[str] = "26.3K"
    comments_count: Optional[str] = "874"
    duration_seconds: int = 15
    language: Optional[str] = "English"
    tone: Optional[str] = "energetic"
    scenes: List[ReelScene] = []
    cta: Optional[str] = ""
    caption: Optional[str] = ""
    hashtags: Optional[List[str]] = []

class ReelGenerationResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    status: str
    message: Optional[str] = None

class ReelJobStatus(BaseModel):
    job_id: str
    status: str
    progress: int
    stage: str
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    audio_url: Optional[str] = None
    script: Optional[dict] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    hook_headline: Optional[str] = None
    hook_highlight: Optional[str] = None
    trending_audio: Optional[str] = None
    creator_name: Optional[str] = None
    follower_count: Optional[str] = None
    likes_count: Optional[str] = None
    comments_count: Optional[str] = None
    provider: Optional[str] = None
    provider_operation_id: Optional[str] = None
    provider_status: Optional[str] = None
    provider_error: Optional[str] = None
    product_category: Optional[str] = None
    generation_mode: Optional[str] = None
    festival_theme: Optional[str] = None
