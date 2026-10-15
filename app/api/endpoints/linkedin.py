import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from pydantic import BaseModel, Field
from bson import ObjectId

from app.core.security import get_current_user
from app.core.database import get_database
from app.services.linkedin_service import LinkedInService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LinkedIn"])


class LinkedInPublishRequest(BaseModel):
    caption: str = Field(default="", description="Post text caption")
    image_url: Optional[str] = Field(default=None, description="Image URL to publish")
    content_id: Optional[str] = Field(default=None, description="Associated content record ID")
    business_id: Optional[str] = Field(default=None, description="Business ID override")


class LinkedInPublishResponse(BaseModel):
    success: bool
    message: str
    post_id: Optional[str] = None
    url: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


@router.post("/publish-image", response_model=LinkedInPublishResponse)
@router.post("/publish", response_model=LinkedInPublishResponse)
@router.post("/post", response_model=LinkedInPublishResponse)
async def linkedin_publish_post(
    request: LinkedInPublishRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Publish an article or text post directly to the user's connected LinkedIn feed.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    result = await LinkedInService.publish_post(
        db=db,
        user_id=user_id,
        caption=request.caption,
        image_url=request.image_url,
        content_id=request.content_id,
        business_id=request.business_id,
    )
    return LinkedInPublishResponse(
        success=True,
        message="Successfully published to LinkedIn!",
        post_id=result.get("post_id"),
        url=result.get("url"),
        data=result,
    )


@router.get("/status")
async def linkedin_get_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get status of LinkedIn connection for current user."""
    uid = str(current_user.get("id") or current_user.get("_id"))
    user_oid = ObjectId(uid) if ObjectId.is_valid(uid) else uid
    
    user_doc = await db["users"].find_one({"_id": user_oid}) if ObjectId.is_valid(uid) else None
    biz_doc = await db["businesses"].find_one({
        "$or": [
            {"ownerId": uid},
            {"ownerId": user_oid},
            {"userId": uid},
            {"userId": user_oid},
        ]
    })
    conn = await db["linkedin_connections"].find_one({"user_id": uid})
    if not conn and user_doc and user_doc.get("email"):
        conn = await db["linkedin_connections"].find_one({"email": user_doc["email"]})
        
    author_id = (
        (biz_doc and biz_doc.get("linkedin_author_id")) or
        (user_doc and user_doc.get("linkedin_author_id")) or
        (conn and conn.get("author_id")) or
        ""
    )
    access_token = (
        (biz_doc and biz_doc.get("linkedin_access_token")) or
        (user_doc and user_doc.get("linkedin_access_token")) or
        (conn and conn.get("access_token")) or
        ""
    )
    connected = bool(
        (biz_doc and biz_doc.get("linkedin_connected")) or
        (user_doc and user_doc.get("linkedin_connected")) or
        (conn and conn.get("connected")) or
        (author_id and access_token)
    )
    return {
        "success": True,
        "connected": connected,
        "linkedin_connected": connected,
        "author_id": author_id,
        "linkedin_author_id": author_id,
        "has_token": bool(access_token),
        "access_token": access_token if access_token else "",
        "linkedin_access_token": access_token if access_token else "",
    }
