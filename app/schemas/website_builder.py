from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, AliasChoices


class ChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    type: Optional[str] = None
    options: Optional[List[Any]] = None
    data: Optional[Any] = None


class CreateSessionRequest(BaseModel):
    language: str = "English"


class SendMessageRequest(BaseModel):
    message: str
    data: Optional[Dict[str, Any]] = None


class ReviseSiteRequest(BaseModel):
    instructions: str


class FrontendSessionResponse(BaseModel):
    sessionId: str
    siteId: Optional[str] = None
    language: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)
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
    current_step: int = 1
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    collected_data: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "active"
    selected_template: Optional[Any] = None
    website_project_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------
# STRUCTURED WEBSITE SCHEMAS
# ---------------------------------------------------------

class WebsiteThemeSchema(BaseModel):
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    font_family: Optional[str] = None
    heading_font: Optional[str] = None
    border_radius: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class WebsiteSectionSchema(BaseModel):
    id: Optional[str] = None
    type: str
    order: Optional[int] = 0
    content: Dict[str, Any] = Field(default_factory=dict)
    styles: Dict[str, Any] = Field(default_factory=dict)
    media: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class WebsitePageSchema(BaseModel):
    id: Optional[str] = None
    name: str
    sections: List[WebsiteSectionSchema] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class WebsiteStateSchema(BaseModel):
    version: int = 1
    theme: Optional[WebsiteThemeSchema] = None
    pages: List[WebsitePageSchema] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------
# WEBSITE EDIT REQUEST / RESPONSE
# ---------------------------------------------------------

class EditWebsiteRequest(BaseModel):

    page_id: Optional[str] = "home"

    user_instruction: str = Field(
        validation_alias=AliasChoices(
            "user_instruction",
            "instruction"
        )
    )

    current_state: Dict[str, Any]

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow"
    )


class EditWebsiteResponse(BaseModel):

    action: str

    target: Optional[str] = None

    changes: Optional[Dict[str, Any]] = None

    message: str

    updated_state: Dict[str, Any]

    model_config = ConfigDict(extra="allow")