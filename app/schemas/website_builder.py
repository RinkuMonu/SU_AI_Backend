from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    type: Optional[str] = None
    options: Optional[List[Any]] = None
    data: Optional[Any] = None

class CreateSessionRequest(BaseModel):
    language: str

class SendMessageRequest(BaseModel):
    message: str
    data: Optional[Any] = None

class ReviseSiteRequest(BaseModel):
    instructions: str

class FrontendSessionResponse(BaseModel):
    sessionId: str
    siteId: Optional[str] = None
    language: Optional[str] = None
    messages: List[Dict[str, Any]]
    generatedSiteData: Optional[Any] = None

class FrontendMessageResponse(BaseModel):
    message: Optional[str] = None
    type: Optional[str] = None
    data: Optional[Any] = None
    messages: Optional[List[Dict[str, Any]]] = None
    siteId: Optional[str] = None
    generatedSiteData: Optional[Any] = None

class WebsiteBuilderSessionResponse(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    language: Optional[str] = None
    current_step: int
    messages: List[Dict[str, Any]]
    collected_data: Dict[str, Any]
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    status: str
    selected_template: Optional[str] = None
    website_project_id: Optional[str] = None
    
    model_config = {
        "populate_by_name": True
    }


# Structured Website Schemas (Phase 1)
class WebsiteThemeSchema(BaseModel):
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    font_family: Optional[str] = None
    heading_font: Optional[str] = None
    border_radius: Optional[str] = None

class WebsiteSectionSchema(BaseModel):
    id: str
    type: str
    order: int
    content: Optional[Dict[str, Any]] = {}
    styles: Optional[Dict[str, Any]] = {}
    media: Optional[Dict[str, Any]] = {}

class WebsitePageSchema(BaseModel):
    id: str
    name: str
    sections: List[WebsiteSectionSchema] = []

class WebsiteStateSchema(BaseModel):
    version: int = 1
    theme: Optional[WebsiteThemeSchema] = None
    pages: List[WebsitePageSchema] = []

class EditWebsiteRequest(BaseModel):
    page_id: Optional[str] = "home"
    user_instruction: str
    current_state: WebsiteStateSchema

class EditWebsiteResponse(BaseModel):
    action: str
    target: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    message: str
    updated_state: WebsiteStateSchema
