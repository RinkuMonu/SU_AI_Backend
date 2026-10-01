from typing import Optional
from app.models.base import MongoBaseModel

class Usage(MongoBaseModel):
    user_id: str
    business_id: Optional[str] = None
    month: str  # YYYY-MM format
    posts_created: int = 0
    reels_created: int = 0
    photoshoots_created: int = 0
    ads_created: int = 0
