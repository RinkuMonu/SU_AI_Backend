from pydantic import Field
from typing import Optional, List
from app.models.base import MongoBaseModel
from datetime import datetime

class SocialIntegration(MongoBaseModel):
    ownerId: str
    businessId: Optional[str] = None
    platform: str
    platformAccountId: str
    accessTokenEncrypted: str
    refreshTokenEncrypted: Optional[str] = None
    tokenExpiresAt: Optional[datetime] = None
    scopes: List[str] = Field(default_factory=list)
    connectionStatus: str = "active"
