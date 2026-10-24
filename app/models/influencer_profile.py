from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
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
    display_name: Optional[str] = None
    creator_name: Optional[str] = None
    bio: Optional[str] = None
    category: Optional[str] = None
    niche: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    preferred_language: Optional[str] = None
    gender: Optional[str] = None
    age_range: Optional[str] = None
    
    # Socials
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    facebook_url: Optional[str] = None
    social_accounts: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Metrics
    follower_count: int = 0
    engagement_rate: float = 0.0
    
    # Collaboration & Content Preferences
    collaboration_preferences: List[str] = Field(default_factory=list)
    content_types: List[str] = Field(default_factory=list)
    media_kit: Optional[Dict[str, Any]] = None
    
    # Portfolio
    portfolio: List[PortfolioItem] = Field(default_factory=list)
    
    profile_image: Optional[str] = None
    profile_photo_url: Optional[str] = None
    cover_image: Optional[str] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
