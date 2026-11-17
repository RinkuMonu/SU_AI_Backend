from typing import Optional
from datetime import datetime
from app.models.base import MongoBaseModel

class RefreshSession(MongoBaseModel):
    userId: str
    hashedToken: str
    expiresAt: datetime
    isRevoked: bool = False
    sessionId: Optional[str] = None
    revokedReason: Optional[str] = None
