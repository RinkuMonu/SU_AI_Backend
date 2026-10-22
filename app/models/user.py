from typing import Optional
from datetime import datetime
from pydantic import EmailStr
from app.models.base import MongoBaseModel


class User(MongoBaseModel):
    name: str
    phone_number: Optional[str] = None
    phone_verified: bool = False
    email: Optional[EmailStr] = None
    email_verified: bool = True
    hashed_password: str
    role: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
