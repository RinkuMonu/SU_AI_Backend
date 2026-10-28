"""
Instagram API schemas for request/response models.
Used for Instagram Login OAuth flow, publishing, comments, messaging, and webhooks.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────────
# OAuth / Connection
# ──────────────────────────────────────────────

class InstagramConnectResponse(BaseModel):
    authorization_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    configured: bool = True
    message: Optional[str] = None


class InstagramStatusResponse(BaseModel):
    connected: bool
    platform: str = "instagram"
    configured: bool = True
    message: Optional[str] = None
    instagram_user_id: Optional[str] = None
    ig_account_id: Optional[str] = None
    username: Optional[str] = None
    ig_username: Optional[str] = None
    account_type: Optional[str] = None
    profile_picture_url: Optional[str] = None
    ig_access_token: Optional[str] = None


class InstagramDisconnectResponse(BaseModel):
    success: bool
    message: str


class InstagramSaveTokenRequest(BaseModel):
    access_token: str = Field(..., description="Instagram Access Token")
    ig_account_id: Optional[str] = None
    ig_username: Optional[str] = None
    user_id: Optional[str] = None


class InstagramExchangeCodeRequest(BaseModel):
    code: str = Field(..., description="Authorization code from Instagram OAuth dialog")
    redirect_uri: Optional[str] = None


class InstagramTokenResponse(BaseModel):
    success: bool
    access_token: str
    token_type: str = "bearer"
    instagram_user_id: Optional[str] = None
    username: Optional[str] = None
    account_type: Optional[str] = None
    profile_picture_url: Optional[str] = None
    expires_in: Optional[int] = None


# ──────────────────────────────────────────────
# Publishing
# ──────────────────────────────────────────────

class InstagramPostRequest(BaseModel):
    model_config = {"populate_by_name": True, "extra": "ignore"}

    content_id: Optional[str] = None
    image_url: Optional[str] = Field(default=None, description="Publicly accessible image URL")
    imageUrl: Optional[str] = None
    media_url: Optional[str] = None
    caption: str = Field(default="", description="Post caption")

    def get_effective_image_url(self) -> str:
        url = self.image_url or self.imageUrl or self.media_url
        if not url:
            return "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80"
        return url


class InstagramReelRequest(BaseModel):
    model_config = {"populate_by_name": True, "extra": "ignore"}

    content_id: Optional[str] = None
    video_url: Optional[str] = Field(default=None, description="Publicly accessible video URL")
    videoUrl: Optional[str] = None
    media_url: Optional[str] = None
    caption: str = Field(default="", description="Reel caption")
    share_to_feed: bool = Field(default=True, description="Share reel to feed")

    def get_effective_video_url(self) -> str:
        url = self.video_url or self.videoUrl or self.media_url
        if not url:
            return "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
        return url


class InstagramCarouselItemRequest(BaseModel):
    media_type: str = Field(default="IMAGE", description="IMAGE or VIDEO")
    media_url: str = Field(..., description="Publicly accessible URL")


class InstagramCarouselRequest(BaseModel):
    content_id: Optional[str] = None
    items: List[InstagramCarouselItemRequest]
    caption: str = Field(default="", description="Carousel caption")


class InstagramPublishResponse(BaseModel):
    success: bool
    ig_media_id: Optional[str] = None
    message: Optional[str] = None


class ContainerStatusResponse(BaseModel):
    id: str
    status: str  # IN_PROGRESS, FINISHED, ERROR


# ──────────────────────────────────────────────
# Comments
# ──────────────────────────────────────────────

class InstagramCommentResponse(BaseModel):
    id: str
    text: str
    username: Optional[str] = None
    timestamp: Optional[str] = None


class InstagramReplyRequest(BaseModel):
    comment_id: str
    message: str


# ──────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────

class InstagramSendMessageRequest(BaseModel):
    recipient_id: str
    message: str


class InstagramConversationResponse(BaseModel):
    id: str
    participants: Optional[List[dict]] = None
    messages: Optional[List[dict]] = None


# ──────────────────────────────────────────────
# Scheduling (extends existing queue schema)
# ──────────────────────────────────────────────

class InstagramScheduleRequest(BaseModel):
    content_id: str
    platform: str = "instagram"
    media_type: str = Field(default="image", description="image or reel")
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    caption: str = ""
    scheduled_for: datetime
