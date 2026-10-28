from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class PlatformConnectionInfo(BaseModel):
    platform: str
    connected: bool = False
    configured: bool = True
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    profile_picture_url: Optional[str] = None
    reauthorization_required: bool = False
    connected_at: Optional[datetime] = None


class SocialOnboardingStatusResponse(BaseModel):
    role: Optional[str] = None
    brand_kit_completed: bool = False
    social_connectivity_completed: bool = False
    social_connectivity_completed_at: Optional[datetime] = None
    should_show_modal: bool = False
    connected_count: int = 0
    platforms: Dict[str, PlatformConnectionInfo] = Field(default_factory=dict)
    create_account_urls: Dict[str, str] = Field(default_factory=dict)


class SocialConnectResponse(BaseModel):
    platform: str
    authorization_url: str
    configured: bool = True
    message: Optional[str] = None



class SocialDisconnectResponse(BaseModel):
    success: bool = True
    platform: str
    message: str
    social_connectivity_completed: bool = False
    should_show_modal: bool = False


class CreateAccountUrlsResponse(BaseModel):
    success: bool = True
    instagram: str = "https://www.instagram.com/accounts/emailsignup/"
    facebook: str = "https://www.facebook.com/r.php"
    linkedin: str = "https://www.linkedin.com/signup"
    urls: Dict[str, str] = Field(default_factory=lambda: {
        "instagram": "https://www.instagram.com/accounts/emailsignup/",
        "facebook": "https://www.facebook.com/r.php",
        "linkedin": "https://www.linkedin.com/signup"
    })
    instructions: str = (
        "Create your account on the official provider website, "
        "then return here and click Connect to authorize and link your account."
    )

