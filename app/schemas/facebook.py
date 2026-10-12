"""
Facebook API Schemas for Facebook Login for Instagram Professionals.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class FacebookConnectResponse(BaseModel):
    authorization_url: str
    scopes: List[str]

class FacebookStatusResponse(BaseModel):
    connected: bool
    platform: str = "facebook"
    fb_page_id: Optional[str] = None
    fb_page_name: Optional[str] = None
    pages: List[Dict[str, Any]] = []
    instagram_business_account: Optional[Dict[str, Any]] = None

class FacebookDisconnectResponse(BaseModel):
    success: bool
    message: str

class FacebookExchangeCodeRequest(BaseModel):
    code: str = Field(..., description="Authorization code from Facebook OAuth dialog")
    redirect_uri: Optional[str] = None

class FacebookTokenResponse(BaseModel):
    success: bool
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    instagram_business_account: Optional[Dict[str, Any]] = None
    pages: List[Dict[str, Any]] = []
