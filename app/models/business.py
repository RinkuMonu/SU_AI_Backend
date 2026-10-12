from pydantic import Field
from typing import Optional, List
from app.models.base import MongoBaseModel

class Business(MongoBaseModel):
    ownerId: str
    businessName: str
    businessType: str
    industry: str
    website: Optional[str] = None
    logoUrl: Optional[str] = None
    brandColors: Optional[List[str]] = None
    preferredLanguage: Optional[str] = None
    targetAudience: Optional[str] = None
    primaryGoal: Optional[str] = None
