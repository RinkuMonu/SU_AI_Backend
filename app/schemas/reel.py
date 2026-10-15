from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class GenerateReelRequest(BaseModel):
    product_id: str = "general"
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    product_image_url: Optional[str] = None
    objective: str
    platform: str = "instagram"
    language: str = "Hinglish"
    duration: int = 15  # seconds
    tone: Optional[str] = "energetic"
    offer: Optional[str] = None
    additional_instruction: Optional[str] = None

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

class ReelScript(BaseModel):
    title: str = "AI Generated Reel"
    objective: Optional[str] = "Engage audience"
    hook: Optional[str] = ""
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
