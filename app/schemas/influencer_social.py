from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class SocialPlatform(str, Enum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"


class ConnectionStatus(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    REVOKED = "REVOKED"


class VerificationMethod(str, Enum):
    OAUTH = "oauth"
    MANUAL = "manual"
    NONE = "none"


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class SocialConnectInitRequest(BaseModel):
    frontend_url: Optional[str] = Field(None, description="Optional custom frontend return URL after OAuth callback")
    rerequest: bool = Field(False, description="Whether to re-request previously declined platform permissions")


class SocialCallbackExchangeRequest(BaseModel):
    code: str = Field(..., description="Official authorization code returned by OAuth provider")
    state: Optional[str] = Field(None, description="CSRF state token for verification")


class SocialDisconnectRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Optional reason for disconnecting the account")


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class SocialConnectInitResponse(BaseModel):
    success: bool = True
    platform: str = Field(..., description="Requested platform ('instagram', 'facebook', 'linkedin')")
    authorization_url: Optional[str] = Field(None, description="Official OAuth authorization URL")
    state: str = Field(..., description="Cryptographic CSRF state token")
    configured: bool = Field(..., description="Whether this platform has valid app credentials configured in environment")
    message: Optional[str] = Field(None, description="Instructional or diagnostic message")


class SocialPlatformConnectionInfo(BaseModel):
    platform: str = Field(..., description="Platform identifier")
    status: str = Field(..., description="One of: NOT_CONNECTED, PENDING, VERIFIED, FAILED, REVOKED")
    platform_account_id: Optional[str] = Field(None, description="Official unique platform user / page ID")
    platform_username: Optional[str] = Field(None, description="Official verified username or handle")
    display_name: Optional[str] = Field(None, description="Display name on the platform")
    profile_url: Optional[str] = Field(None, description="Link to the verified profile")
    verification_method: str = Field("none", description="Method used to verify ('oauth', 'manual', 'none')")
    is_verified: bool = Field(False, description="Whether identity and ownership was verified via official OAuth API")
    connected_at: Optional[datetime] = Field(None, description="Timestamp of when connection was first established")
    verified_at: Optional[datetime] = Field(None, description="Timestamp of official ownership verification")
    last_error: Optional[str] = Field(None, description="Last error description if status is FAILED")


class InfluencerSocialStatusResponse(BaseModel):
    success: bool = True
    platforms: Dict[str, SocialPlatformConnectionInfo] = Field(
        ...,
        description="Current connection status across all supported platforms (instagram, facebook, linkedin)"
    )
    total_connected: int = Field(..., description="Total accounts currently connected or in progress")
    total_verified: int = Field(..., description="Total accounts with verified ownership via OAuth")
    should_show_prompt: bool = Field(
        ...,
        description="Whether the frontend should prompt the influencer to connect accounts (True if 0 verified accounts and not dismissed)"
    )
    dismissed_popup: bool = Field(
        False,
        description="Whether the creator has dismissed or skipped the post-onboarding social connection prompt"
    )
    dismissed_at: Optional[datetime] = Field(None, description="Timestamp when creator dismissed the prompt")


class SocialCallbackResponse(BaseModel):
    success: bool = True
    platform: str = Field(..., description="Platform connected")
    status: str = Field("VERIFIED", description="Connection status after callback")
    platform_username: Optional[str] = Field(None, description="Verified username")
    platform_account_id: Optional[str] = Field(None, description="Official platform account ID")
    profile_url: Optional[str] = Field(None, description="Public profile URL")
    message: str = Field(..., description="User-facing status message")


class SocialDisconnectResponse(BaseModel):
    success: bool = True
    platform: str = Field(..., description="Disconnected platform")
    status: str = Field("NOT_CONNECTED", description="Updated connection status")
    message: str = Field(..., description="Status message")


class DismissSocialPromptResponse(BaseModel):
    success: bool = True
    dismissed_popup: bool = True
    dismissed_at: datetime
    message: str = Field("Social connection prompt dismissed successfully.", description="Status message")
