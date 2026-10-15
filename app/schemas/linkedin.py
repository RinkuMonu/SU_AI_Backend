"""
LinkedIn API Schemas for OAuth, connection status, token exchange, and publishing.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class LinkedInConnectResponse(BaseModel):
    authorization_url: str
    scopes: List[str]

class LinkedInStatusResponse(BaseModel):
    connected: bool
    platform: str = "linkedin"
    linkedin_id: Optional[str] = None
    author_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    profile_picture_url: Optional[str] = None
    access_token: Optional[str] = None

class LinkedInDisconnectResponse(BaseModel):
    success: bool
    message: str

class LinkedInExchangeCodeRequest(BaseModel):
    code: str = Field(..., description="Authorization code from LinkedIn OAuth dialog")
    redirect_uri: Optional[str] = None

class LinkedInSaveTokenRequest(BaseModel):
    access_token: str = Field(..., description="LinkedIn Access Token")
    author_id: Optional[str] = None
    name: Optional[str] = None

class LinkedInTokenResponse(BaseModel):
    success: bool
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    author_id: Optional[str] = None
    user_info: Optional[Dict[str, Any]] = None

class LinkedInPublishRequest(BaseModel):
    text: str = Field(..., description="Post commentary/text")
    image_url: Optional[str] = None
    content_id: Optional[str] = None

class LinkedInPublishResponse(BaseModel):
    success: bool
    message: str
    post_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
