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

router = APIRouter(prefix="/api/linkedin", tags=["LinkedIn"])


@router.get("/connect")
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

    if LinkedInService.is_demo_mode():
        logger.info(f"[DEMO MODE] LinkedIn connect initiated for user {user_id}")
        return {
            "authorization_url": f"http://localhost:8000/api/linkedin/callback?code=demo_li_code&state={state}"
        }

    auth_url = LinkedInService.get_authorization_url(state=state)
    return {"authorization_url": auth_url}


@router.get("/callback")
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

    # Validate and consume state token
    state_doc = await db["linkedin_oauth_states"].find_one_and_delete({"state": state})
    if not state_doc:
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_error=Invalid+state+token"
        )

    user_id = state_doc["user_id"]

    # Demo mode handling
    if LinkedInService.is_demo_mode():
        logger.info(f"[DEMO MODE] LinkedIn callback processing for user {user_id}")
        now = datetime.now(timezone.utc)
        demo_connection = {
            "user_id": user_id,
            "platform": "linkedin",
            "linkedin_author_id": DEMO_LI_AUTHOR_ID,
            "display_name": DEMO_LI_DISPLAY_NAME,
            "account_type": "PROFILE",
            "profile_picture_url": "",
            "encrypted_access_token": encrypt_token("DEMO_LI_TOKEN"),
            "connected": True,
            "created_at": now,
            "updated_at": now,
        }
        await db["linkedin_connections"].update_one(
            {"user_id": user_id, "platform": "linkedin"},
            {"$set": demo_connection},
            upsert=True
        )

        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "linkedin_author_id": DEMO_LI_AUTHOR_ID,
                "linkedin_access_token": "DEMO_LI_TOKEN",
                "linkedin_account_name": DEMO_LI_DISPLAY_NAME,
                "updated_at": now,
            }},
            upsert=True
        )

        # Sync onboarding completion
        await sync_business_social_status(db, user_id)

        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/linkedin?linkedin_connected=true"
        )

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


@router.get("/status")
async def linkedin_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Check LinkedIn connection status.
    Never exposes raw tokens, secrets, or encrypted blobs.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await LinkedInService.get_connection(db, user_id)

    if conn:
        return {
            "connected": True,
            "platform": "linkedin",
            "account_id": conn.get("linkedin_author_id"),
            "display_name": conn.get("display_name"),
            "account_type": conn.get("account_type", "PROFILE"),
            "profile_picture_url": conn.get("profile_picture_url"),
        }

    return {
        "connected": False,
        "platform": "linkedin",
        "account_id": None,
        "display_name": None,
    }


@router.post("/disconnect")
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


@router.get("/signup-url")
@router.get("/create-account-url")
async def linkedin_signup_url():
    """Returns official LinkedIn member signup URL."""
    return {
        "platform": "linkedin",
        "url": "https://www.linkedin.com/signup",
        "official_signup_url": "https://www.linkedin.com/signup",
        "instructions": "Create your LinkedIn account on the official website, then return and connect it."
    }

