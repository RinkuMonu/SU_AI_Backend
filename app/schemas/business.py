from pydantic import BaseModel, Field
from typing import Optional, List

class BusinessCreate(BaseModel):
    businessName: str
    businessType: str
    industry: str
    website: Optional[str] = None
    preferredLanguage: Optional[str] = None
    targetAudience: Optional[str] = None
    primaryGoal: Optional[str] = None

class BusinessUpdate(BaseModel):
    businessName: Optional[str] = None
    businessType: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    logoUrl: Optional[str] = None
    brandColors: Optional[List[str]] = None
    preferredLanguage: Optional[str] = None
    targetAudience: Optional[str] = None
    primaryGoal: Optional[str] = None

class BusinessResponse(BaseModel):
    id: str
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
