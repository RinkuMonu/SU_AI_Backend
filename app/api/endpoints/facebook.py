import secrets
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from bson import ObjectId

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.services.facebook_service import FacebookService, FACEBOOK_LOGIN_PERMISSIONS
from app.schemas.facebook import (
    FacebookConnectResponse,
    FacebookStatusResponse,
    FacebookDisconnectResponse,
    FacebookExchangeCodeRequest,
    FacebookTokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])

@router.get("/connect", response_model=FacebookConnectResponse)
async def facebook_connect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Generate Facebook Login OAuth URL for Instagram Professionals with permissions:
    - pages_show_list
    - instagram_basic
    - instagram_content_publish
    - pages_read_engagement
    - instagram_manage_comments
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    state = secrets.token_urlsafe(32)

    await db["facebook_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    })

    if FacebookService.is_demo_mode():
        logger.info(f"[DEMO MODE] Facebook connect for user {user_id}")
        callback_uri = f"{settings.BACKEND_URL}/api/facebook/callback?code=demo_fb_code&state={state}"
        return FacebookConnectResponse(
            authorization_url=callback_uri,
            scopes=FACEBOOK_LOGIN_PERMISSIONS,
        )

    auth_url = FacebookService.get_authorization_url(state=state)
    return FacebookConnectResponse(
        authorization_url=auth_url,
        scopes=FACEBOOK_LOGIN_PERMISSIONS,
    )

@router.get("/callback")
async def facebook_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_reason: str = Query(None),
    error_description: str = Query(None),
    db=Depends(get_database),
):
    """
    Facebook OAuth callback endpoint.
    Exchanges authorization code for long-lived access token,
    discovers Facebook Pages and linked Instagram Professional Account,
    and updates business/user connection state.
    """
    frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()

    if error:
        err_msg = error_description or error
        logger.warning(f"Facebook OAuth callback error: {err_msg}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={err_msg}")

    if not code:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=missing_code")

    # Demo mode handling
    if FacebookService.is_demo_mode():
        demo_user_id = "60a7b45c342d3c148c2e6d5a"
        if state:
            state_doc = await db["facebook_oauth_states"].find_one_and_delete({"state": state})
            if state_doc and "user_id" in state_doc:
                demo_user_id = state_doc["user_id"]

        demo_token = "DEMO_FB_ACCESS_TOKEN"
        demo_pages = {
            "pages": [
                {
                    "page_id": "100000000000001",
                    "page_name": "Demo Business Page",
                    "page_access_token": "DEMO_PAGE_TOKEN",
                    "category": "Retail",
                    "instagram_business_account": {
                        "id": "17841400000000001",
                        "username": "demo_business_ig",
                        "name": "Demo Instagram Professional",
                        "account_type": "BUSINESS",
                        "profile_picture_url": "",
                        "followers_count": 1250,
                        "media_count": 48,
                    },
                }
            ],
            "instagram_account": {
                "id": "17841400000000001",
                "username": "demo_business_ig",
                "name": "Demo Instagram Professional",
                "account_type": "BUSINESS",
                "profile_picture_url": "",
                "followers_count": 1250,
                "media_count": 48,
                "linked_page_id": "100000000000001",
                "linked_page_name": "Demo Business Page",
                "page_access_token": "DEMO_PAGE_TOKEN",
            },
        }

        await FacebookService.save_connection(
            db=db,
            user_id=demo_user_id,
            token_data={"access_token": demo_token, "expires_in": 5184000},
            pages_data=demo_pages,
        )

        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true&fb_access_token={demo_token}"
        )

    # Validate state parameter
    oauth_state = await db["facebook_oauth_states"].find_one_and_delete({"state": state})
    if not oauth_state:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=invalid_state")

    user_id = oauth_state["user_id"]

    try:
        # 1. Exchange code for long-lived access token
        token_data = await FacebookService.exchange_code_for_token(code)
        access_token = token_data["access_token"]

        # 2. Fetch user's pages and linked Instagram Professional Account
        pages_data = await FacebookService.get_facebook_pages_and_instagram(access_token)

        # 3. Save connection into database
        await FacebookService.save_connection(db, user_id, token_data, pages_data)

        ig_account = pages_data.get("instagram_account")
        ig_param = f"&ig_username={ig_account.get('username')}" if ig_account else ""

        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true&fb_access_token={access_token}{ig_param}"
        )
    except HTTPException as e:
        logger.error(f"Facebook callback failed: {e.detail}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={e.detail}")
    except Exception as e:
        logger.error(f"Unexpected error in Facebook callback: {e}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=token_exchange_failed")

@router.post("/exchange-token", response_model=FacebookTokenResponse)
async def exchange_facebook_code(
    payload: FacebookExchangeCodeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Direct JSON API endpoint to exchange authorization code for access token.
    Returns access token, pages, and linked Instagram Professional account details.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))

    if FacebookService.is_demo_mode():
        demo_token = "DEMO_FB_ACCESS_TOKEN"
        demo_pages = {
            "pages": [
                {
                    "page_id": "100000000000001",
                    "page_name": "Demo Business Page",
                    "category": "Retail",
                }
            ],
            "instagram_account": {
                "id": "17841400000000001",
                "username": "demo_business_ig",
                "account_type": "BUSINESS",
            },
        }
        await FacebookService.save_connection(
            db=db,
            user_id=user_id,
            token_data={"access_token": demo_token, "expires_in": 5184000},
            pages_data=demo_pages,
        )
        return FacebookTokenResponse(
            success=True,
            access_token=demo_token,
            expires_in=5184000,
            instagram_business_account=demo_pages["instagram_account"],
            pages=demo_pages["pages"],
        )

    # Real token exchange
    token_data = await FacebookService.exchange_code_for_token(payload.code)
    access_token = token_data["access_token"]
    pages_data = await FacebookService.get_facebook_pages_and_instagram(access_token)
    await FacebookService.save_connection(db, user_id, token_data, pages_data)

    return FacebookTokenResponse(
        success=True,
        access_token=access_token,
        expires_in=token_data.get("expires_in"),
        instagram_business_account=pages_data.get("instagram_account"),
        pages=pages_data.get("pages", []),
    )

@router.get("/token")
async def get_facebook_access_token(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Direct endpoint to retrieve current active Facebook Access Token and linked Instagram Account.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    try:
        token = await FacebookService.get_access_token(db, user_id)
        connection = await FacebookService.get_connection(db, user_id)
        return {
            "success": True,
            "access_token": token,
            "token_type": "bearer",
            "connection": connection,
        }
    except HTTPException:
        if FacebookService.is_demo_mode():
            return {
                "success": True,
                "access_token": "DEMO_FB_ACCESS_TOKEN",
                "token_type": "bearer",
                "demo_mode": True,
                "connection": {
                    "connected": True,
                    "fb_page_id": "100000000000001",
                    "instagram_business_account": {
                        "id": "17841400000000001",
                        "username": "demo_business_ig",
                    },
                },
            }
        raise

@router.get("/status", response_model=FacebookStatusResponse)
async def facebook_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Check Facebook & linked Instagram Professional Account connection status.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await FacebookService.get_connection(db, user_id)

    if conn:
        return FacebookStatusResponse(
            connected=True,
            fb_page_id=conn.get("fb_page_id"),
            fb_page_name=conn.get("fb_page_name"),
            pages=conn.get("pages", []),
            instagram_business_account=conn.get("instagram_business_account"),
        )

    return FacebookStatusResponse(connected=False)

@router.post("/disconnect", response_model=FacebookDisconnectResponse)
async def facebook_disconnect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Disconnect Facebook & linked Instagram connection for current account."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id

    # 1. Clear businesses collection
    business_query = {"$or": [{"user_id": user_id}, {"owner_id": user_id}, {"userId": user_id}]}
    await db["businesses"].update_one(
        business_query,
        {
            "$unset": {
                "fb_access_token": "",
                "fb_access_token_encrypted": "",
                "fb_page_id": "",
                "fb_page_name": "",
                "fb_pages": "",
                "fb_token_expires_at": "",
            },
            "$set": {"fb_connected": False},
        },
    )

    # 2. Clear users collection
    await db["users"].update_one(
        {"_id": oid},
        {
            "$unset": {
                "facebook_access_token": "",
            },
            "$set": {"facebook_connected": False},
        },
    )

    return FacebookDisconnectResponse(
        success=True,
        message="Facebook connection disconnected successfully",
    )
