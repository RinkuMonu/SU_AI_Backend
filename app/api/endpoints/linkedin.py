from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import secrets
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.services.linkedin_service import (
    LinkedInService,
    DEMO_LI_AUTHOR_ID,
    DEMO_LI_DISPLAY_NAME,
)
from app.services.social_connectivity_service import sync_business_social_status
from app.services.instagram_service import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LinkedIn"])


@router.get("/auth-url", operation_id="linkedin_auth_url")
@router.get("/connect", operation_id="linkedin_connect")
async def linkedin_connect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Initiate LinkedIn OAuth 2.0 flow.
    Stores CSRF state in DB and returns the official authorization URL.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    state = secrets.token_urlsafe(32)

    await db["linkedin_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    })

    if not LinkedInService.is_configured():
        logger.info(f"LinkedIn connect requested for user {user_id}, but LinkedIn credentials are not configured.")
        return {
            "authorization_url": None,
            "platform": "linkedin",
            "configured": False,
            "message": "LinkedIn integration is not configured. Missing LINKEDIN_CLIENT_ID or LINKEDIN_CLIENT_SECRET.",
        }

    auth_url = LinkedInService.get_authorization_url(state=state)
    return {
        "authorization_url": auth_url,
        "platform": "linkedin",
        "configured": True,
        "state": state,
    }


@router.get("/callback", operation_id="linkedin_callback")
async def linkedin_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    db=Depends(get_database),
):
    """
    LinkedIn OAuth callback endpoint.
    Exchanges code for access token, retrieves member info, persists connection,
    and updates onboarding completion state.
    """
    frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()

    if error:
        logger.warning(f"LinkedIn OAuth error: {error} - {error_description}")
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error={error_description or error}"
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error=Missing+code+or+state"
        )

    if not LinkedInService.is_configured():
        logger.warning("LinkedIn OAuth callback attempted while LinkedIn credentials are not configured.")
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error=LinkedIn+integration+is+not+configured"
        )

    # Validate and consume state token
    state_doc = await db["linkedin_oauth_states"].find_one_and_delete({"state": state})
    if not state_doc:
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error=Invalid+state+token"
        )

    user_id = state_doc["user_id"]

    # Real OAuth flow
    try:
        token_data = await LinkedInService.exchange_code_for_token(code)
        profile = await LinkedInService.get_linkedin_profile(token_data["access_token"])
        await LinkedInService.save_connection(db, user_id, token_data, profile)

        # Sync onboarding completion
        await sync_business_social_status(db, user_id)

        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_connected=true"
        )
    except HTTPException as e:
        logger.error(f"LinkedIn callback HTTP exception: {e.detail}")
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error={e.detail}"
        )
    except Exception as e:
        logger.error(f"LinkedIn callback unexpected error: {e}")
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error=Connection+failed"
        )


@router.get("/status", operation_id="linkedin_get_status")
async def linkedin_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Check LinkedIn connection status.
    Never exposes raw tokens, secrets, or encrypted blobs.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    is_conf = LinkedInService.is_configured()
    conn = await LinkedInService.get_connection(db, user_id)

    if conn and conn.get("connected"):
        return {
            "connected": True,
            "configured": is_conf,
            "platform": "linkedin",
            "account_id": conn.get("linkedin_author_id"),
            "display_name": conn.get("display_name"),
            "account_type": conn.get("account_type", "PROFILE"),
            "profile_picture_url": conn.get("profile_picture_url"),
        }

    return {
        "connected": False,
        "configured": is_conf,
        "platform": "linkedin",
        "account_id": None,
        "display_name": None,
    }


@router.post("/disconnect", operation_id="linkedin_disconnect_account")
async def linkedin_disconnect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Disconnect LinkedIn account and update onboarding status.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    success = await LinkedInService.disconnect(db, user_id)
    is_social_completed, _ = await sync_business_social_status(db, user_id)

    return {
        "success": True,
        "message": "LinkedIn disconnected successfully" if success else "No active LinkedIn connection",
        "platform": "linkedin",
        "social_connectivity_completed": is_social_completed,
    }


@router.get("/signup-url", operation_id="linkedin_get_signup_url")
@router.get("/create-account-url", operation_id="linkedin_get_create_account_url")
async def linkedin_signup_url():
    """Returns official LinkedIn member signup URL."""
    return {
        "platform": "linkedin",
        "url": "https://www.linkedin.com/signup",
        "official_signup_url": "https://www.linkedin.com/signup",
        "instructions": "Create your LinkedIn account on the official website, then return and connect it."
    }

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


@router.post("/publish-image", response_model=LinkedInPublishResponse, operation_id="linkedin_publish_image_post")
@router.post("/publish", response_model=LinkedInPublishResponse, operation_id="linkedin_publish_general_post")
@router.post("/post", response_model=LinkedInPublishResponse, operation_id="linkedin_publish_text_post")
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


