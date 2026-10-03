from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone

class PortfolioItem(BaseModel):
    title: str
    description: Optional[str] = None
    media_url: str
    platform: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class InfluencerProfile(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    username: Optional[str] = None
    bio: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    gender: Optional[str] = None
    age_range: Optional[str] = None
    
    # Socials
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    facebook_url: Optional[str] = None
    
    # Metrics
    follower_count: int = 0
    engagement_rate: float = 0.0
    
    # Portfolio
    portfolio: List[PortfolioItem] = Field(default_factory=list)
    
    profile_image: Optional[str] = None
    cover_image: Optional[str] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
