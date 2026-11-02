from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# ---------------------------------------------------------------------------
# Step Request Models (Partial updates with progressive preservation)
# ---------------------------------------------------------------------------

class ProfileStepRequest(BaseModel):
    full_name: Optional[str] = Field(None, description="Creator's display or full name", min_length=1, max_length=100)
    username: Optional[str] = Field(None, description="Unique creator handle (3-30 chars, alphanumeric and underscores)")
    bio: Optional[str] = Field(None, description="Creator bio / about", max_length=1000)
    location: Optional[str] = Field(None, description="City / Region / Country", max_length=100)
    gender: Optional[str] = Field(None, description="Gender identity (e.g. Male, Female, Non-binary, Prefer not to say)")
    profile_image: Optional[str] = Field(None, description="Profile photo URL or uploaded image path")


class NichesStepRequest(BaseModel):
    niches: Optional[List[str]] = Field(default_factory=list, description="List of selected niche IDs or names")
    primary_niche: Optional[str] = Field(None, description="Primary focus niche")
    custom_niche: Optional[str] = Field(None, description="User-entered custom niche if any", max_length=60)


class SocialPlatformItem(BaseModel):
    handle: Optional[str] = Field(None, description="Username or handle on the platform")
    url: Optional[str] = Field(None, description="Profile URL on the platform")
    connected: bool = Field(False, description="Whether the account is connected or linked")
    verified: bool = Field(False, description="Whether ownership has been verified")


class SocialAccountsStepRequest(BaseModel):
    instagram: Optional[SocialPlatformItem] = Field(None, description="Instagram profile details")
    youtube: Optional[SocialPlatformItem] = Field(None, description="YouTube channel details")
    tiktok: Optional[SocialPlatformItem] = Field(None, description="TikTok profile details")
    facebook: Optional[SocialPlatformItem] = Field(None, description="Facebook page or profile details")


class GoalsStepRequest(BaseModel):
    goals: Optional[List[str]] = Field(default_factory=list, description="List of selected creator goals on DhandaGrow")


class ProgressStepRequest(BaseModel):
    current_step: int = Field(..., ge=1, le=7, description="Current active onboarding screen (1-7)")
    completed_steps: Optional[List[int]] = Field(None, description="List of completed step numbers")


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class UsernameCheckResponse(BaseModel):
    available: bool = Field(..., description="Whether the requested username is available")
    username: str = Field(..., description="Normalized username checked")
    message: str = Field(..., description="Validation feedback message")


class InfluencerOnboardingStateResponse(BaseModel):
    success: bool = True
    user_id: str
    onboarding_status: str = Field(..., description="'NOT_STARTED', 'IN_PROGRESS', or 'COMPLETED'")
    current_step: int = Field(1, description="Active onboarding screen number (1-7)")
    completed_steps: List[int] = Field(default_factory=list, description="Array of completed screen numbers")
    profile: Dict[str, Any] = Field(default_factory=dict, description="Saved profile details")
    niches: Dict[str, Any] = Field(default_factory=dict, description="Saved niches details")
    social_accounts: Dict[str, Any] = Field(default_factory=dict, description="Saved social account connections")
    goals: List[str] = Field(default_factory=list, description="Saved creator goals")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class InfluencerReviewResponse(BaseModel):
    success: bool = True
    user_id: str
    can_complete: bool = Field(..., description="Whether all required fields are satisfied to finalize onboarding")
    missing_requirements: List[str] = Field(default_factory=list, description="Any missing prerequisite fields")
    summary: Dict[str, Any] = Field(..., description="Complete review payload for Screen 6")


class OnboardingCompleteResponse(BaseModel):
    success: bool = True
    message: str
    redirect_url: str = Field("/influencer", description="Target destination route after successful onboarding")
    user_id: str
    onboarding_status: str = "COMPLETED"
    profile: Dict[str, Any] = Field(default_factory=dict)


class AvatarUploadResponse(BaseModel):
    success: bool = True
    url: str
    filename: str
    message: str = "Avatar uploaded successfully"

