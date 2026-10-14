"""
Facebook API Schemas for Facebook Login for Instagram Professionals.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class FacebookConnectResponse(BaseModel):
    authorization_url: str
    scopes: List[str]

class FacebookStatusResponse(BaseModel):
    connected: bool
    platform: str = "facebook"
    fb_page_id: Optional[str] = None
    fb_page_name: Optional[str] = None
    page_access_token: Optional[str] = None
    user_access_token: Optional[str] = None
    pages: List[Dict[str, Any]] = []
    instagram_business_account: Optional[Dict[str, Any]] = None

class FacebookDisconnectResponse(BaseModel):
    success: bool
    message: str

class FacebookExchangeCodeRequest(BaseModel):
    code: str = Field(..., description="Authorization code from Facebook OAuth dialog")
    redirect_uri: Optional[str] = None

class FacebookSaveTokenRequest(BaseModel):
    access_token: str = Field(..., description="Facebook Access Token")
    fb_page_id: Optional[str] = None
    fb_page_name: Optional[str] = None
    page_access_token: Optional[str] = None
    user_access_token: Optional[str] = None

class FacebookTokenResponse(BaseModel):
    success: bool
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    instagram_business_account: Optional[Dict[str, Any]] = None
    pages: List[Dict[str, Any]] = []

class FacebookPublishRequest(BaseModel):
    image_url: Optional[str] = None
    caption: str = ""
    content_id: Optional[str] = None

class FacebookPublishResponse(BaseModel):
    success: bool
    message: str
    post_id: Optional[str] = None
    url: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

class FacebookVerifyTokenResponse(BaseModel):
    valid: bool
    has_publish_permission: bool
    page_id: Optional[str] = None
    page_name: Optional[str] = None
    scopes: List[str] = []
    missing_permissions: List[str] = []
    message: str

