from pydantic import Field
from typing import Optional, Any
from app.models.base import MongoBaseModel

class Project(MongoBaseModel):
    ownerId: str
    businessId: Optional[str] = None
    toolType: str
    title: str
    prompt: str
    outputData: Optional[Any] = None
    outputUrl: Optional[str] = None
    status: str = "pending"
