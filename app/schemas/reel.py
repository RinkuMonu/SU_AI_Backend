from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

class GenerateReelRequest(BaseModel):
    # Creation Mode
    creation_mode: Optional[str] = "product_image"  # "product_image", "text_prompt", "product", "creative"
    generation_mode: Optional[str] = "product"  # Legacy support

    # Product Identification & Context
    product_id: Optional[str] = "general"
    product_name: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[str] = None
    product_category: Optional[str] = None  # Legacy alias
    subcategory: Optional[str] = None
    subcategory_id: Optional[str] = None
    product_description: Optional[str] = None
    price: Optional[float] = None
    sale_price: Optional[float] = None
    product_attributes: Optional[Dict[str, Any]] = None

    # Visual Assets & Enhancement
    image_id: Optional[str] = None
    image_url: Optional[str] = None
    product_image_url: Optional[str] = None  # Legacy alias
    enhance_image: bool = False
    enhancement_prompt: Optional[str] = None

    # Video Specifications
    duration: int = 15  # 15, 30, 45, 60 seconds
    duration_seconds: Optional[int] = None  # Alias
    language: str = "Hinglish"
    platform: str = "instagram_reels"  # "instagram_reels", "facebook_reels", "youtube_shorts"
    aspect_ratio: Optional[str] = "9:16"
    generation_mode: Optional[str] = "product"  # "product" (default) or "creative"
    custom_prompt: Optional[str] = None
    video_style: Optional[str] = None

    # Audio & Narration
    voiceover_mode: str = "ai"  # "none", "ai", "uploaded"
    voice_tone: Optional[str] = "energetic"  # "professional", "friendly", "energetic", "premium", "conversational", "storytelling"
    tone: Optional[str] = "energetic"  # Legacy alias
    voice: Optional[str] = None
    uploaded_audio_id: Optional[str] = None
    uploaded_audio_url: Optional[str] = None
    music_style: Optional[str] = "cinematic"  # "none", "soft", "corporate", "cinematic", "upbeat", "festive", "elegant", "energetic"
    captions_enabled: bool = True

    # Marketing Campaign & Offer
    campaign_objective: Optional[str] = "product_showcase"  # "flash_sale", "product_launch", "festival_special", "brand_story", etc.
    objective: Optional[str] = "sale"  # Legacy alias
    discount_type: Optional[str] = None  # "percentage", "fixed", "buy_one_get_one"
    discount_value: Optional[str] = None
    promo_code: Optional[str] = None
    offer_start_date: Optional[str] = None
    offer_end_date: Optional[str] = None
    offer_terms: Optional[str] = None
    offer_text: Optional[str] = None
    offer: Optional[str] = None  # Legacy alias

    # Creative Directives & Festivals
    additional_instructions: Optional[str] = None
    additional_instruction: Optional[str] = None  # Legacy alias
    prompt: Optional[str] = None  # Common alias
    festival_theme: Optional[str] = "none"  # "none", "diwali", "holi", "eid", "christmas", "new_year"

    # Brand Kit Mode
    use_brand_kit: bool = Field(
        default=False,
        description="Whether to use the authenticated user's saved Brand Kit"
    )

    @model_validator(mode="before")
    @classmethod
    def harmonize_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Sync duration
        if "duration_seconds" in values and values["duration_seconds"]:
            values["duration"] = int(values["duration_seconds"])

        # Sync image URLs
        img = values.get("image_url") or values.get("product_image_url") or values.get("image_id")
        if img:
            values["image_url"] = img
            values["product_image_url"] = img

        # Sync category
        cat = values.get("category") or values.get("product_category") or values.get("category_id")
        if cat:
            values["category"] = cat
            values["product_category"] = cat

        # Sync objective
        obj = values.get("campaign_objective") or values.get("objective")
        if obj:
            values["campaign_objective"] = obj
            values["objective"] = obj

        # Sync tone
        tone = values.get("voice_tone") or values.get("tone")
        if tone:
            values["voice_tone"] = tone
            values["tone"] = tone

        # Sync instructions
        instr = values.get("additional_instructions") or values.get("additional_instruction") or values.get("prompt")
        if instr:
            values["additional_instructions"] = instr
            values["additional_instruction"] = instr

        # Sync offer
        off = values.get("offer_text") or values.get("offer")
        if off:
            values["offer_text"] = off
            values["offer"] = off

        # Sync voiceover mode & uploaded audio
        vm = values.get("voiceover_mode") or values.get("voiceover_type")
        if vm:
            values["voiceover_mode"] = "uploaded" if vm == "upload" else vm

        aud = values.get("uploaded_audio_url") or values.get("voice_audio_url")
        if aud:
            values["uploaded_audio_url"] = aud

        # Sync music style
        bgm = values.get("music_style") or values.get("background_music")
        if bgm:
            values["music_style"] = bgm

        # Sync enhancement prompt
        enh_prompt = values.get("enhancement_prompt") or values.get("image_enhancement_prompt")
        if enh_prompt:
            values["enhancement_prompt"] = enh_prompt

        # Sync custom prompt
        cp = values.get("custom_prompt")
        if cp and not values.get("additional_instructions"):
            values["additional_instructions"] = cp

        # Sync discount type and value
        dt = values.get("discount_type") or values.get("offer_type")
        if dt:
            values["discount_type"] = dt
        dv = values.get("discount_value") or values.get("offer_discount")
        if dv:
            values["discount_value"] = dv

        # Normalize creation mode
        mode = values.get("creation_mode") or values.get("generation_mode") or "product"
        if mode in ["product", "product_image"]:
            values["creation_mode"] = "product_image"
        elif mode in ["prompt", "text_prompt", "creative"]:
            values["creation_mode"] = "text_prompt"

        return values

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v):
        allowed_durations = [5, 6, 8, 10, 15, 20, 30, 45, 60]
        if v not in allowed_durations:
            # Fall back to nearest allowed or default 15
            closest = min(allowed_durations, key=lambda x: abs(x - v))
            return closest
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v):
        # Allow any string, default to Hinglish if empty
        return (v or "Hinglish").strip().capitalize()


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
    original_image_url: Optional[str] = None
    enhanced_image_url: Optional[str] = None
    creation_mode: Optional[str] = None
    campaign_objective: Optional[str] = None
    platform: Optional[str] = None
    duration: Optional[int] = None
    language: Optional[str] = None
    voiceover_mode: Optional[str] = None
    music_style: Optional[str] = None
    captions_enabled: Optional[bool] = None
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
    quality_report: Optional[Dict[str, Any]] = None
    motion_classification: Optional[str] = None
    motion_score: Optional[float] = None
    diversity_score: Optional[float] = None
    use_brand_kit: Optional[bool] = False
    brand_kit_applied: Optional[bool] = False
    brand: Optional[Dict[str, Any]] = None


class EnhanceImageRequest(BaseModel):
    image_url: str
    prompt: Optional[str] = None
    product_name: Optional[str] = None
    category: Optional[str] = None
    skip_enhancement: bool = False


class EnhanceImageResponse(BaseModel):
    success: bool
    original_image_url: str
    enhanced_image_url: str
    enhanced: bool
    provider: str
    message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
