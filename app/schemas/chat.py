from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class AttachmentMetadata(BaseModel):
    url: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None

class MessageCreate(BaseModel):
    text: Optional[str] = Field(None, max_length=4000, description="Message text (max 4000 chars)")
    message_type: str = Field(default="text", description="Type of message: text, attachment, proposal, system")
    attachments: List[AttachmentMetadata] = Field(default_factory=list, description="Optional attachment metadata")

class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_role: Optional[str] = None
    message_type: str = "text"
    text: str = ""
    attachments: List[AttachmentMetadata] = []
    read: bool = False
    read_at: Optional[str] = None
    created_at: str

class ParticipantSummary(BaseModel):
    user_id: str
    name: str
    username: Optional[str] = None
    avatar: Optional[str] = None
    role: Optional[str] = None

class ConversationCreate(BaseModel):
    business_user_id: Optional[str] = None
    creator_user_id: Optional[str] = None
    target_user_id: Optional[str] = None
    collaboration_id: Optional[str] = None
    campaign_id: Optional[str] = None
    initial_message: Optional[str] = None

class ConversationResponse(BaseModel):
    id: str
    business_user_id: str
    creator_user_id: str
    collaboration_id: Optional[str] = None
    campaign_id: Optional[str] = None
    last_message: Optional[str] = None
    last_message_at: Optional[str] = None
    unread_counts: Dict[str, int] = Field(default_factory=dict)
    unread_count: int = 0
    status: str = "active"
    created_at: str
    updated_at: str
    other_participant: Optional[ParticipantSummary] = None

class RecommendedBusiness(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    logo: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

class ConversationListResponse(BaseModel):
    success: bool = True
    data: List[ConversationResponse] = []
    recommended_businesses: List[RecommendedBusiness] = []
    unread_total: int = 0

class ReadReceiptResponse(BaseModel):
    success: bool = True
    conversation_id: str
    unread_count: int = 0
    message: str = "Messages marked as read"
