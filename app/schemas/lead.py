from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


class LeadCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, description="Full name of the contact")
    email: EmailStr = Field(..., description="Email address")
    subject: str = Field(..., min_length=2, max_length=250, description="Inquiry subject")
    message: str = Field(..., min_length=5, max_length=5000, description="Message content")
    phone: Optional[str] = Field(None, max_length=30, description="Optional contact phone number")
    source: Optional[str] = Field("website_contact_form", description="Lead source identifier")


class LeadUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, description="Status: new, contacted, in_progress, qualified, closed")
    notes: Optional[str] = Field(None, max_length=2000, description="Internal admin/handling notes")
    assigned_to: Optional[str] = Field(None, max_length=150, description="Assigned staff member")


class LeadResponse(BaseModel):
    id: str
    name: str
    email: str
    subject: str
    message: str
    phone: Optional[str] = None
    source: str = "website_contact_form"
    status: str = "new"
    notes: Optional[str] = None
    assigned_to: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LeadSubmitResponse(BaseModel):
    success: bool = True
    message: str
    lead_id: str
    data: Optional[LeadResponse] = None


class LeadListResponse(BaseModel):
    success: bool = True
    total: int
    page: int
    limit: int
    total_pages: int
    data: List[LeadResponse]
