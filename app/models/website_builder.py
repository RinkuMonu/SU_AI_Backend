from typing import Optional, List, Dict, Any
from app.models.base import MongoBaseModel
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str
    content: str
    quick_actions: Optional[List[str]] = None

class WebsiteProject(MongoBaseModel):
    user_id: str
    business_id: Optional[str] = None
    business_name: Optional[str] = None
    session_id: str
    template_id: Optional[str] = None
    language: str
    theme: Optional[Dict[str, Any]] = None
    pages: List[Dict[str, Any]] = []
    status: str = "draft"  # collecting, ready, generating, draft, published, failed
    version: int = 1
    website_data: Optional[Dict[str, Any]] = None

class WebsiteBuilderSession(MongoBaseModel):
    user_id: str
    language: Optional[str] = None
    current_step: int = 1
    messages: List[Dict[str, Any]] = []
    collected_data: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    selected_template: Optional[Any] = None
    website_project_id: Optional[str] = None
    status: str = "active"
