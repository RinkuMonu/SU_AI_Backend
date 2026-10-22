from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.base import MongoBaseModel

class SocialConnection(MongoBaseModel):
    user_id: str
    business_id: Optional[str] = None
    platform: str  # "instagram" | "facebook" | "linkedin"
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    account_type: Optional[str] = None  # e.g., "BUSINESS", "PAGE", "PROFILE"
    profile_picture_url: Optional[str] = None
    encrypted_access_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    connected: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
