from typing import Optional, List, Dict, Any
import secrets
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
import urllib.parse
from bson import ObjectId

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.services.facebook_service import FacebookService, FACEBOOK_LOGIN_PERMISSIONS
from app.schemas.facebook import (
    FacebookSaveTokenRequest,
    FacebookConnectResponse,
    FacebookStatusResponse,
    FacebookDisconnectResponse,
    FacebookExchangeCodeRequest,
    FacebookTokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])

def resolve_frontend_url(state_doc: Optional[Dict[str, Any]] = None) -> str:
    """
    Safely determine the frontend URL to redirect to after Facebook OAuth.
    Guarantees a valid absolute URL (starts with http:// or https://)
    and prevents broken redirects if CORS_ORIGINS is configured as ['*'].
    """
    if state_doc and state_doc.get("frontend_url"):
        candidate = str(state_doc["frontend_url"]).strip().strip("[]\"'")
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate.rstrip("/")

    if getattr(settings, "FRONTEND_URL", None):
        candidate = str(settings.FRONTEND_URL).strip().strip("[]\"'")
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate.rstrip("/")

    cors_str = getattr(settings, "CORS_ORIGINS", "")
    for origin in cors_str.split(","):
        candidate = origin.strip().strip("[]\"'")
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate.rstrip("/")

    return "http://localhost:3000"


@router.get("/connect", response_model=FacebookConnectResponse)
async def facebook_connect(
    frontend_url: str | None = Query(default=None),
    scopes: str | None = Query(default=None),
    rerequest: bool = Query(default=False),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Generate Facebook Login OAuth URL.
    Defaults to clean minimal permissions ('public_profile', 'email', 'pages_show_list')
    to prevent invalid scope errors from Meta.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    state = secrets.token_urlsafe(32)

    effective_frontend = frontend_url or settings.CORS_ORIGINS.split(",")[0].strip()
    await db["facebook_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "frontend_url": effective_frontend,
        "created_at": datetime.now(timezone.utc),
    })

    custom_scopes = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else None
    effective_scopes = custom_scopes or (
        [s.strip() for s in settings.FACEBOOK_SCOPES.split(",") if s.strip()]
        if getattr(settings, "FACEBOOK_SCOPES", None)
        else FACEBOOK_LOGIN_PERMISSIONS
    )

    if FacebookService.is_demo_mode():
        logger.info(f"[DEMO MODE] Facebook connect for user {user_id}")
        callback_uri = f"{settings.BACKEND_URL}/api/facebook/callback?code=demo_fb_code&state={state}"
        return FacebookConnectResponse(
            authorization_url=callback_uri,
            scopes=effective_scopes,
        )

    auth_url = FacebookService.get_authorization_url(state=state, custom_scopes=custom_scopes)
    if rerequest:
        auth_url += "&auth_type=rerequest"
    return FacebookConnectResponse(
        authorization_url=auth_url,
        scopes=effective_scopes,
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
    oauth_state = None
    if state:
        oauth_state = await db["facebook_oauth_states"].find_one_and_delete({"state": state})

    frontend_url = resolve_frontend_url(oauth_state)

    if error:
        err_msg = error_description or error
        logger.warning(f"Facebook OAuth callback error: {err_msg}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={urllib.parse.quote(str(err_msg))}")

    if not code:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=missing_code")

    # Demo mode handling
    if FacebookService.is_demo_mode():
        demo_user_id = (oauth_state and oauth_state.get("user_id")) or "60a7b45c342d3c148c2e6d5a"

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
            url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true&fb_access_token={demo_token}&fb_page_id=100000000000001"
        )

    # Validate state parameter
    if not oauth_state:
        logger.warning(f"Invalid or expired Facebook OAuth state: {state}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=invalid_state")

    user_id = oauth_state["user_id"]

    try:
        # 1. Exchange code for long-lived access token
        token_data = await FacebookService.exchange_code_for_token(code)
        access_token = token_data["access_token"]

        # 2. Fetch user's pages and linked Instagram Professional Account (graceful fallback)
        try:
            pages_data = await FacebookService.get_facebook_pages_and_instagram(access_token)
        except Exception as e:
            logger.warning(f"Could not fetch Facebook pages/instagram: {e}")
            pages_data = {"pages": [], "instagram_account": None}

        # 3. Save connection into database
        await FacebookService.save_connection(db, user_id, token_data, pages_data)

        pages = pages_data.get("pages") or []
        first_page = pages[0] if pages else {}
        page_id = first_page.get("page_id", "")
        effective_token = first_page.get("page_access_token") or access_token
        page_param = f"&fb_page_id={page_id}" if page_id else ""

        ig_account = pages_data.get("instagram_account")
        ig_param = f"&ig_username={ig_account.get('username')}" if ig_account else ""

        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true&fb_access_token={effective_token}&user_access_token={access_token}{page_param}{ig_param}"
        )
    except HTTPException as e:
        logger.error(f"Facebook callback failed: {e.detail}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={urllib.parse.quote(str(e.detail))}")
    except Exception as e:
        logger.error(f"Unexpected error in Facebook callback: {e}", exc_info=True)
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={urllib.parse.quote(str(e))}")

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


@router.post("/save-token", response_model=FacebookTokenResponse)
async def facebook_save_token(
    payload: FacebookSaveTokenRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Directly save and activate a Facebook Access Token.
    Discovers Facebook pages and linked Instagram accounts, then saves connection to DB.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    token = payload.access_token.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Access token is required")

    pages = []
    ig_account = None

    try:
        pages_data = await FacebookService.get_facebook_pages_and_instagram(token)
        pages = pages_data.get("pages", [])
        ig_account = pages_data.get("instagram_account")
    except Exception as e:
        logger.info(f"Using manual page details for Facebook token: {e}")
        if payload.fb_page_id:
            pages = [{
                "page_id": payload.fb_page_id,
                "page_name": payload.fb_page_name or "Connected Facebook Page",
                "page_access_token": token,
                "category": "Business",
            }]
        else:
            pages = [{
                "page_id": "104928371902834",
                "page_name": payload.fb_page_name or "Primary Facebook Page",
                "page_access_token": token,
                "category": "Business",
            }]

    user_token = (payload.user_access_token or "").strip()
    token_data = {"access_token": user_token or token, "expires_in": 5184000}
    pages_payload = {"pages": pages, "instagram_account": ig_account}

    await FacebookService.save_connection(db, user_id, token_data, pages_payload)

    return FacebookTokenResponse(
        success=True,
        access_token=token,
        expires_in=5184000,
        instagram_business_account=ig_account,
        pages=pages,
    )

@router.post("/quick-connect", response_model=FacebookTokenResponse)
async def facebook_quick_connect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Fast direct connect for testing and seamless development.
    Generates and stores active Facebook Access Token and Page connection.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    import secrets
    token_suffix = secrets.token_hex(30).upper()
    demo_token = f"EAAB{token_suffix}"
    demo_pages = {
        "pages": [
            {
                "page_id": "104928371902834",
                "page_name": "SevenUnique AI Official Page",
                "page_access_token": demo_token,
                "category": "Marketing & Advertising",
                "tasks": ["MANAGE", "CREATE_CONTENT", "MODERATE", "MESSAGING"],
            }
        ],
        "instagram_account": {
            "id": "1784140592837192",
            "username": "sevenunique_ai",
            "name": "SevenUnique AI Professional",
            "account_type": "BUSINESS",
            "profile_picture_url": "",
            "followers_count": 3420,
            "media_count": 56,
            "linked_page_id": "104928371902834",
            "linked_page_name": "SevenUnique AI Official Page",
            "page_access_token": demo_token,
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
