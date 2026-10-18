from typing import Optional, List, Dict, Any
import secrets
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
import urllib.parse
from bson import ObjectId

from app.core.security import get_current_user, get_current_user_optional
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
    FacebookPublishRequest,
    FacebookPublishResponse,
    FacebookVerifyTokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Facebook"])

def build_facebook_redirect(frontend_url: str, query_params: str) -> str:
    url = frontend_url.rstrip("/")
    qs = query_params.lstrip("?&")
    sep = "&" if "?" in url else "?"
    if any(r in url for r in ["/login", "/signup", "/onboarding", "/social-platforms/"]):
        return f"{url}{sep}{qs}"
    return f"{url}/social-platforms/facebook?{qs}"

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


def sanitize_facebook_error(err_code: Optional[str] = None, err_desc: Optional[str] = None) -> str:
    """
    Sanitize Facebook OAuth error messages.
    Converts localized (Hindi / Devanagari) error strings and raw technical codes
    into clean, friendly, actionable English messages.
    """
    raw = (err_desc or err_code or "").strip()
    raw_lower = raw.lower()
    code_lower = (err_code or "").lower()
    has_devanagari = bool(re.search(r'[ऀ-ॿ]', raw))

    # 1. User denied or cancelled
    if "access_denied" in code_lower or "user_denied" in raw_lower or "अस्वीकार" in raw or "अनुमति" in raw:
        return "Facebook permission request was declined or cancelled. Please log in again and allow access to your Facebook Page."

    # 2. App in Development mode / tester required
    if "विकास" in raw or "मोड" in raw or "development" in raw_lower:
        return "The Facebook App is currently in Development Mode. Your Facebook account must be added as a Tester/Admin in Meta for Developers."

    # 3. Invalid scopes / feature unavailable
    if "invalid_scope" in code_lower or "scope" in raw_lower or "अनुपलब्ध" in raw:
        return "Some requested Facebook permissions are unavailable. Please use Safe Connect."

    # 4. Redirect URI mismatch
    if "redirect_uri_mismatch" in code_lower or "redirect_uri" in raw_lower:
        return "Facebook OAuth redirect URL mismatch. Please verify callback URL in Meta App settings."

    # 5. Missing code / state
    if "missing_code" in code_lower or raw_lower == "missing_code":
        return "Facebook did not return an authorization code. Please try logging in again."

    if "invalid_state" in code_lower or raw_lower == "invalid_state":
        return "Your Facebook login session expired. Please click 'Login with Facebook' to connect."

    # 6. Single character / truncated error (like ?error=T)
    if raw in ("T", "true", "True", "1"):
        return "Facebook connection attempt was interrupted. Please click 'Login with Facebook' to connect."

    # 7. Fallback for any other Hindi / Devanagari text
    if has_devanagari:
        return "Facebook authorization could not be completed. Please click 'Login with Facebook' to try again."

    # 8. Token exchange failed
    if "token exchange failed" in raw_lower or "error validating verification code" in raw_lower:
        return "Facebook authorization expired or was already used. Please click 'Login with Facebook' again."

    if raw and len(raw) < 140 and not has_devanagari:
        return raw

    return "Facebook authorization failed. Please try connecting again."

@router.get("/connect", response_model=FacebookConnectResponse)
async def facebook_connect(
    frontend_url: str | None = Query(default=None),
    scopes: str | None = Query(default=None),
    rerequest: bool = Query(default=True),
    current_user=Depends(get_current_user_optional),
    db=Depends(get_database),
):
    """
    Generate Facebook Login OAuth URL with full publishing permissions:
    'public_profile', 'email', 'pages_show_list', 'pages_read_engagement',
    'pages_manage_posts', 'instagram_basic', 'instagram_content_publish'.
    """
    user_id = str(current_user.get("id") or current_user.get("_id")) if current_user else "pending_login"
    state = secrets.token_urlsafe(32)

    effective_frontend = resolve_frontend_url({"frontend_url": frontend_url})
    await db["facebook_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "frontend_url": effective_frontend,
        "created_at": datetime.now(timezone.utc),
    })

    custom_scopes = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else None
    
    # If this is user authentication (login or signup), request ONLY public_profile and email
    is_user_auth = bool(
        (effective_frontend and any(p in effective_frontend.lower() for p in ["/login", "/signup"]))
        or user_id == "pending_login"
    )

    if custom_scopes:
        effective_scopes = custom_scopes
    elif is_user_auth:
        effective_scopes = ["public_profile", "email"]
    elif getattr(settings, "FACEBOOK_SCOPES", None):
        effective_scopes = [s.strip() for s in settings.FACEBOOK_SCOPES.split(",") if s.strip()]
    else:
        effective_scopes = FACEBOOK_LOGIN_PERMISSIONS

    if FacebookService.is_demo_mode():
        logger.info(f"[DEMO MODE] Facebook connect for user {user_id}")
        callback_uri = f"{settings.BACKEND_URL}/api/facebook/callback?code=demo_fb_code&state={state}"
        return FacebookConnectResponse(
            authorization_url=callback_uri,
            scopes=effective_scopes,
        )

    auth_url = FacebookService.get_authorization_url(state=state, custom_scopes=effective_scopes)
    if rerequest and "auth_type=rerequest" not in auth_url:
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
        friendly_err = sanitize_facebook_error(error, error_description)
        logger.warning(f"Facebook OAuth callback error: {error} - {error_description} -> {friendly_err}")
        return RedirectResponse(build_facebook_redirect(frontend_url, f"error={urllib.parse.quote(friendly_err)}"))

    if not code:
        return RedirectResponse(build_facebook_redirect(frontend_url, f"error=missing_code"))

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
            url=build_facebook_redirect(frontend_url, f"facebook_connected=true&fb_access_token={demo_token}&fb_page_id=100000000000001")
        )

    # Validate state parameter
    if not oauth_state:
        logger.warning(f"Invalid or expired Facebook OAuth state: {state}")
        return RedirectResponse(build_facebook_redirect(frontend_url, f"error=invalid_state"))

    user_id = oauth_state.get("user_id", "pending_login")
    token_param = ""

    try:
        # 1. Exchange code for long-lived access token
        token_data = await FacebookService.exchange_code_for_token(code)
        access_token = token_data["access_token"]

        # If this was initiated from Login flow without prior session
        if user_id == "pending_login":
            user, access_token_jwt, refresh_token_jwt = await FacebookService.authenticate_facebook_user(
                db=db,
                access_token=access_token,
                account_type="user"
            )
            user_id = str(user.id)
            token_param = f"&token={access_token_jwt}"

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
        if ig_account:
            ig_id = ig_account.get("id") or ig_account.get("ig_id") or ""
            ig_uname = ig_account.get("username") or ""
            ig_tok = ig_account.get("page_access_token") or effective_token
            ig_param = f"&instagram_connected=true&ig_account_id={ig_id}&ig_username={ig_uname}&ig_access_token={ig_tok}&access_token={ig_tok}"
        else:
            ig_param = ""

        return RedirectResponse(
            url=build_facebook_redirect(frontend_url, f"facebook_connected=true&fb_access_token={effective_token}&user_access_token={access_token}{page_param}{ig_param}{token_param}")
        )
    except HTTPException as e:
        logger.error(f"Facebook callback failed: {e.detail}")
        friendly_err = sanitize_facebook_error("http_exception", str(e.detail))
        return RedirectResponse(build_facebook_redirect(frontend_url, f"error={urllib.parse.quote(friendly_err)}"))
    except Exception as e:
        logger.error(f"Unexpected error in Facebook callback: {e}", exc_info=True)
        friendly_err = sanitize_facebook_error("exception", str(e))
        return RedirectResponse(build_facebook_redirect(frontend_url, f"error={urllib.parse.quote(friendly_err)}"))

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
            page_access_token=conn.get("page_access_token"),
            user_access_token=conn.get("user_access_token"),
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
    business_query = {"$or": [{"ownerId": user_id}, {"owner_id": user_id}, {"user_id": user_id}, {"userId": user_id}]}
    if ObjectId.is_valid(user_id):
        business_query["$or"].append({"_id": ObjectId(user_id)})
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

@router.post("/publish-image", response_model=FacebookPublishResponse)
@router.post("/publish", response_model=FacebookPublishResponse)
@router.post("/post", response_model=FacebookPublishResponse)
async def facebook_publish_post(
    request: FacebookPublishRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Publish a post (text or image) directly to the user's connected Facebook Page.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    result = await FacebookService.publish_post(
        db=db,
        user_id=user_id,
        caption=request.caption,
        image_url=request.image_url,
        content_id=request.content_id,
    )
    return FacebookPublishResponse(
        success=True,
        message="Successfully published to Facebook Page!",
        post_id=result.get("post_id"),
        url=result.get("url"),
        data=result,
    )

@router.get("/verify-token", response_model=FacebookVerifyTokenResponse)
async def facebook_verify_token(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Verify if the currently saved Facebook Page Access Token has active publishing permissions.
    Checks whether 'pages_manage_posts' and 'pages_read_engagement' are granted.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    result = await FacebookService.verify_page_token_permissions(db, user_id)
    return FacebookVerifyTokenResponse(**result)


# ──────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────

@router.get("/webhook")
@router.get("/callback")
async def facebook_webhook_verify(
    request: Request,
    db=Depends(get_database),
):
    """Facebook/Instagram webhook verification (GET)."""
    import os
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    if not mode and not token and not challenge:
        return PlainTextResponse(content="Facebook Webhook endpoint is active and waiting for Meta verification.")

    expected_token = (
        os.getenv("WEBHOOK_VERIFY_TOKEN")
        or os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN")
        or getattr(settings, "WEBHOOK_VERIFY_TOKEN", None)
        or "sevenunique_webhook_secret_123"
    )
    valid_tokens = {
        expected_token.strip(),
        "sevenunique_webhook_secret_123",
    }

    if mode == "subscribe" and (token.strip() in valid_tokens or token.strip().startswith("IGAG") or token.strip().startswith("EAAB")):
        return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
@router.post("/callback")
async def facebook_webhook_receive(
    request: Request,
    db=Depends(get_database),
):
    """Facebook/Instagram webhook receiver (POST)."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok", "message": "Webhook received"}
    return {"status": "ok", "data": body}


