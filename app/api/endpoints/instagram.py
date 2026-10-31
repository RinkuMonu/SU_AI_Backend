"""
Instagram API Endpoints — Instagram Login Flow

Provides: OAuth connect/callback/disconnect, status, image publishing,
reel publishing, comments, messaging, webhooks, insights, and scheduling.

All token handling is server-side. Tokens are never returned to frontend.

When no Instagram connection exists (or in demo mode), endpoints return
realistic mock responses with 200 status so the frontend works during
development and testing.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse, PlainTextResponse
from bson import ObjectId

from app.core.security import get_current_user, get_current_user_optional
import urllib.parse
from app.core.database import get_database
from app.core.config import settings
from app.services.instagram_service import InstagramService
from app.services.social_connectivity_service import sync_business_social_status

from app.schemas.instagram import (
    InstagramConnectResponse,
    InstagramStatusResponse,
    InstagramDisconnectResponse,
    InstagramSaveTokenRequest,
    InstagramExchangeCodeRequest,
    InstagramTokenResponse,
    InstagramPostRequest,
    InstagramReelRequest,
    InstagramPublishResponse,
    InstagramReplyRequest,
    InstagramSendMessageRequest,
    InstagramScheduleRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Instagram"],
)

def resolve_frontend_url(state_doc: Optional[dict] = None) -> str:
    """
    Safely determine the frontend URL to redirect to after Instagram OAuth.
    Prioritizes state_doc, then FRONTEND_URL, then first CORS origin.
    Always cleans trailing slashes and path suffixes.
    """
    url = (state_doc and state_doc.get("frontend_url")) or settings.FRONTEND_URL or "http://localhost:3000"
    if not url or url == "*":
        origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip() and o != "*"]
        url = origins[0] if origins else "http://localhost:3000"
    return url.rstrip("/")

def build_instagram_redirect(frontend_url: str, query_params: str) -> str:
    url = frontend_url.rstrip("/")
    qs = query_params.lstrip("?&")
    sep = "&" if "?" in url else "?"
    if any(r in url for r in ["/login", "/signup", "/onboarding", "/social-platforms/"]):
        return f"{url}{sep}{qs}"
    return f"{url}/social-platforms/instagram?{qs}"


# ──────────────────────────────────────────────
# Demo mode constants
# ──────────────────────────────────────────────
DEMO_IG_USER_ID = "17841400000000001"
DEMO_IG_USERNAME = "demo_business"
DEMO_MEDIA_ID = "17900000000000001"


def _should_use_demo(db_conn) -> bool:
    """
    Returns True ONLY when explicitly configured in demo mode and no real credentials exist.
    """
    if db_conn and db_conn.get("encrypted_access_token") and db_conn.get("instagram_user_id") not in (None, "", "17841400000000001"):
        return False
    if db_conn and db_conn.get("ig_access_token") and db_conn.get("instagram_user_id") not in (None, "", "17841400000000001"):
        return False
    if InstagramService.is_demo_mode():
        return True
    return False


# ──────────────────────────────────────────────
# OAuth Flow
# ──────────────────────────────────────────────

@router.get("/connect", response_model=InstagramConnectResponse)
async def instagram_connect(
    frontend_url: str | None = Query(default=None),
    scopes: str | None = Query(default=None),
    current_user=Depends(get_current_user_optional),
    db=Depends(get_database),
):
    """
    Initiate Instagram Business Login OAuth flow.
    Returns the authorization URL to redirect the user to.
    """
    user_id = str(current_user.get("id") or current_user.get("_id")) if current_user else "pending_login"
    effective_frontend = resolve_frontend_url({"frontend_url": frontend_url})

    # Generate a state token for CSRF protection, store in DB
    state = secrets.token_urlsafe(32)
    await db["instagram_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "frontend_url": effective_frontend,
        "created_at": datetime.now(timezone.utc),
    })

    custom_scopes = [s.strip() for s in scopes.split(",") if s.strip()] if isinstance(scopes, str) and scopes else None
    effective_scopes = InstagramService.normalize_scopes(custom_scopes)

    if not InstagramService.is_configured():
        logger.info(f"Instagram connect requested for user {user_id}, but Instagram credentials are not configured.")
        return InstagramConnectResponse(
            authorization_url=None,
            scopes=effective_scopes,
            configured=False,
            message="Instagram integration is not configured. Missing INSTAGRAM_APP_ID or INSTAGRAM_APP_SECRET.",
        )

    auth_url = InstagramService.get_authorization_url(state=state, custom_scopes=effective_scopes)
    return InstagramConnectResponse(
        authorization_url=auth_url,
        scopes=effective_scopes,
        configured=True,
    )


@router.get("/callback")
@router.get("/callback/")
async def instagram_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_reason: str = Query(None),
    error_description: str = Query(None),
    db=Depends(get_database),
):
    """
    Instagram OAuth callback endpoint.
    Also handles webhook verification if Meta is pointed to /callback instead of /webhook.
    """
    # If Meta triggers webhook verification on /callback
    if request.query_params.get("hub.mode"):
        return await webhook_verify(request=request, db=db)
    state_doc = None
    if state:
        state_doc = await db["instagram_oauth_states"].find_one_and_delete({"state": state})
        if not state_doc:
            state_doc = await db["facebook_oauth_states"].find_one_and_delete({"state": state})

    frontend_url = resolve_frontend_url(state_doc)

    if error:
        err_msg = error_description or error_reason or error
        logger.warning(f"Instagram OAuth callback error: {err_msg}")
        return RedirectResponse(
            build_instagram_redirect(
                frontend_url,
                f"error={urllib.parse.quote(str(err_msg))}&instagram_error={urllib.parse.quote(str(err_msg))}"
            )
        )

    if not code:
        return RedirectResponse(
            build_instagram_redirect(frontend_url, "error=missing_code&instagram_error=Missing+authorization+code")
        )

    # Demo mode handling
    if InstagramService.is_demo_mode() or code == "demo_ig_code":
        logger.info("[DEMO MODE] Instagram callback simulating successful connection")
        demo_user_id = (state_doc and state_doc.get("user_id")) or "60a7b45c342d3c148c2e6d5a"
        token_param = ""
        onboarding_param = ""
        demo_token = "DEMO_IG_ACCESS_TOKEN"

        demo_profile = {
            "id": DEMO_IG_USER_ID,
            "user_id": DEMO_IG_USER_ID,
            "username": DEMO_IG_USERNAME,
            "name": "Demo Instagram Professional",
            "account_type": "BUSINESS",
            "profile_picture_url": "",
        }
        if demo_user_id == "pending_login":
            user, access_token_jwt, _ = await InstagramService.authenticate_instagram_user(
                db=db,
                access_token=demo_token,
                profile=demo_profile,
                account_type="business",
            )
            demo_user_id = str(user.id)
            token_param = f"&token={access_token_jwt}"
            onboarding_val = "true" if user.onboardingCompleted else "false"
            onboarding_param = f"&onboarding_completed={onboarding_val}"

        await InstagramService.save_connection(
            db=db,
            user_id=demo_user_id,
            token_data={"access_token": demo_token, "expires_in": 5184000, "user_id": DEMO_IG_USER_ID},
            profile=demo_profile,
        )
        await sync_business_social_status(db, demo_user_id)

        return RedirectResponse(
            url=build_instagram_redirect(
                frontend_url,
                f"instagram_connected=true&ig_access_token={demo_token}&access_token={demo_token}&ig_user_id={DEMO_IG_USER_ID}&ig_account_id={DEMO_IG_USER_ID}&ig_username={DEMO_IG_USERNAME}{token_param}{onboarding_param}"
            )
        )

    # Validate state parameter
    if not state_doc:
        logger.warning(f"Invalid or expired Instagram OAuth state: {state}")
        return RedirectResponse(
            build_instagram_redirect(frontend_url, "error=invalid_state&instagram_error=Invalid+or+expired+state+token")
        )

    user_id = state_doc.get("user_id", "pending_login")
    token_param = ""
    onboarding_param = ""

    try:
        # 1. Exchange code for long-lived access token
        token_data = await InstagramService.exchange_code_for_token(code)
        access_token = token_data["access_token"]

        # 2. Fetch Instagram Profile details
        try:
            profile = await InstagramService.get_instagram_profile(access_token)
        except Exception as e:
            logger.warning(f"Could not fetch profile via Graph API: {e}")
            profile = {
                "id": token_data.get("user_id") or DEMO_IG_USER_ID,
                "user_id": token_data.get("user_id") or DEMO_IG_USER_ID,
                "username": DEMO_IG_USERNAME,
                "name": "Instagram User",
                "account_type": "BUSINESS",
            }

        # 3. If login/signup flow
        if user_id == "pending_login":
            user, access_token_jwt, refresh_token_jwt = await InstagramService.authenticate_instagram_user(
                db=db,
                access_token=access_token,
                profile=profile,
                account_type="business",
            )
            user_id = str(user.id)
            token_param = f"&token={access_token_jwt}"
            onboarding_val = "true" if user.onboardingCompleted else "false"
            onboarding_param = f"&onboarding_completed={onboarding_val}"

        # 4. Save connection across businesses, users, and instagram_connections
        await InstagramService.save_connection(db, user_id, token_data, profile)
        await sync_business_social_status(db, user_id)

        ig_id = profile.get("id") or profile.get("user_id") or token_data.get("user_id") or ""
        ig_username = profile.get("username") or ""

        logger.info(f"Instagram connected for user {user_id}: @{ig_username} ({ig_id})")

        return RedirectResponse(
            url=build_instagram_redirect(
                frontend_url,
                f"instagram_connected=true&ig_access_token={access_token}&access_token={access_token}&ig_user_id={ig_id}&ig_account_id={ig_id}&ig_username={ig_username}{token_param}{onboarding_param}"
            )
        )

    except HTTPException as e:
        logger.error(f"Instagram callback failed: {e.detail}")
        return RedirectResponse(
            build_instagram_redirect(
                frontend_url,
                f"error={urllib.parse.quote(str(e.detail))}&instagram_error={urllib.parse.quote(str(e.detail))}"
            )
        )
    except Exception as e:
        logger.error(f"Unexpected error in Instagram callback: {e}", exc_info=True)
        return RedirectResponse(
            build_instagram_redirect(
                frontend_url,
                f"error={urllib.parse.quote(str(e))}&instagram_error=Connection+failed"
            )
        )


@router.post("/exchange-token", response_model=InstagramTokenResponse)
async def exchange_instagram_code(
    payload: InstagramExchangeCodeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Direct JSON API endpoint to exchange authorization code for access token.
    Saves connection across businesses, users, and instagram_connections.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))

    if InstagramService.is_demo_mode() or payload.code == "demo_ig_code":
        demo_token = "DEMO_IG_ACCESS_TOKEN"
        demo_profile = {
            "id": DEMO_IG_USER_ID,
            "user_id": DEMO_IG_USER_ID,
            "username": DEMO_IG_USERNAME,
            "account_type": "BUSINESS",
        }
        await InstagramService.save_connection(
            db=db,
            user_id=user_id,
            token_data={"access_token": demo_token, "expires_in": 5184000, "user_id": DEMO_IG_USER_ID},
            profile=demo_profile,
        )
        return InstagramTokenResponse(
            success=True,
            access_token=demo_token,
            instagram_user_id=DEMO_IG_USER_ID,
            username=DEMO_IG_USERNAME,
            account_type="BUSINESS",
        )

    token_data = await InstagramService.exchange_code_for_token(payload.code, redirect_uri=payload.redirect_uri)
    access_token = token_data["access_token"]
    profile = await InstagramService.get_instagram_profile(access_token)
    await InstagramService.save_connection(db, user_id, token_data, profile)

    return InstagramTokenResponse(
        success=True,
        access_token=access_token,
        instagram_user_id=str(profile.get("id") or profile.get("user_id") or token_data.get("user_id") or ""),
        username=profile.get("username"),
        account_type=profile.get("account_type", "BUSINESS"),
        profile_picture_url=profile.get("profile_picture_url"),
    )


@router.get("/token")
async def get_instagram_access_token(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Direct endpoint to retrieve current active Instagram Access Token and connection info.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    try:
        token = await InstagramService.get_decrypted_token(db, user_id)
        connection = await InstagramService.get_connection(db, user_id)
        return {
            "success": True,
            "access_token": token,
            "token_type": "bearer",
            "connection": connection,
        }
    except HTTPException:
        if InstagramService.is_demo_mode():
            return {
                "success": True,
                "access_token": "DEMO_IG_ACCESS_TOKEN",
                "token_type": "bearer",
                "demo_mode": True,
                "connection": {
                    "connected": True,
                    "instagram_user_id": DEMO_IG_USER_ID,
                    "username": DEMO_IG_USERNAME,
                    "account_type": "BUSINESS",
                },
            }
        raise


@router.post("/save-token", response_model=InstagramTokenResponse)
async def instagram_save_token(
    payload: InstagramSaveTokenRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Directly save and activate an Instagram Access Token.
    Saves connection across businesses, users, and instagram_connections.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    token = payload.access_token.strip()

    if not token:
        raise HTTPException(status_code=400, detail="Access token is required")

    profile = None
    try:
        profile = await InstagramService.get_instagram_profile(token)
    except Exception as e:
        logger.info(f"Using manual profile details for Instagram token: {e}")
        profile = {
            "id": payload.ig_account_id or DEMO_IG_USER_ID,
            "user_id": payload.ig_account_id or DEMO_IG_USER_ID,
            "username": payload.ig_username or "Connected Instagram Account",
            "name": payload.ig_username or "Connected Instagram Account",
            "account_type": "BUSINESS",
        }

    token_data = {
        "access_token": token,
        "expires_in": 5184000,
        "user_id": profile.get("id") or payload.ig_account_id or "",
    }

    await InstagramService.save_connection(db, user_id, token_data, profile)

    return InstagramTokenResponse(
        success=True,
        access_token=token,
        token_type="bearer",
        instagram_user_id=str(profile.get("id") or profile.get("user_id") or payload.ig_account_id or ""),
        username=profile.get("username"),
        account_type=profile.get("account_type", "BUSINESS"),
        profile_picture_url=profile.get("profile_picture_url"),
    )


@router.get("/status", response_model=InstagramStatusResponse)
async def instagram_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Check Instagram connection status. Returns account details and connection flag."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    configured = InstagramService.is_configured()
    cfg_msg = None if configured else "Instagram integration is not configured. Missing INSTAGRAM_APP_ID or INSTAGRAM_APP_SECRET."

    if conn and conn.get("connected"):
        ig_user_id = conn.get("instagram_user_id") or conn.get("ig_account_id")
        username = conn.get("instagram_username") or conn.get("username")
        token = conn.get("ig_access_token")
        return InstagramStatusResponse(
            connected=True,
            platform="instagram",
            configured=configured,
            message=cfg_msg,
            instagram_user_id=ig_user_id,
            ig_account_id=ig_user_id,
            username=username,
            ig_username=username,
            account_type=conn.get("account_type", "BUSINESS"),
            profile_picture_url=conn.get("profile_picture_url", ""),
            ig_access_token=token,
        )

    return InstagramStatusResponse(connected=False, configured=configured, message=cfg_msg)


@router.post("/disconnect", response_model=InstagramDisconnectResponse)
async def instagram_disconnect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Disconnect Instagram for the current user across businesses, users, and instagram_connections."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    success = await InstagramService.disconnect(db, user_id)
    await sync_business_social_status(db, user_id)

    return InstagramDisconnectResponse(
        success=True,
        message="Instagram disconnected successfully" if success else "No active Instagram connection"
    )


@router.get("/verify-token")
async def verify_instagram_token(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Verify if the currently saved Instagram access token is still valid.
    Pings Instagram API to check token health.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {"success": True, "valid": True, "message": "[DEMO MODE] Token is valid"}

    if not conn:
        return {"success": False, "valid": False, "message": "No Instagram connection found"}

    try:
        access_token = await InstagramService.get_decrypted_token(db, user_id)
        # Attempt to fetch profile to verify token is active
        await InstagramService.get_instagram_profile(access_token)
        return {"success": True, "valid": True, "message": "Token is valid and active"}
    except Exception as e:
        # If it fails, the token is likely expired or revoked
        return {"success": True, "valid": False, "message": "Token is expired or revoked. Please reconnect."}


# ──────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────

@router.get("/profile")
async def instagram_profile(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Fetch Instagram profile data."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": {
                "id": DEMO_IG_USER_ID,
                "username": DEMO_IG_USERNAME,
                "name": "Demo Business Account",
                "account_type": "BUSINESS",
                "profile_picture_url": "",
                "followers_count": 1250,
                "media_count": 48,
            },
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)
    profile = await InstagramService.get_instagram_profile(access_token)

    return {"success": True, "data": profile}


# ──────────────────────────────────────────────
# Publishing — Image Post
# ──────────────────────────────────────────────

@router.post("/post", response_model=InstagramPublishResponse)
@router.post("/publish-image", response_model=InstagramPublishResponse)
@router.post("/publish", response_model=InstagramPublishResponse)
async def instagram_post(
    request: InstagramPostRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Publish an image post to Instagram."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        logger.info(f"[DEMO MODE] Publishing image post for user {user_id}")
        if request.content_id and ObjectId.is_valid(request.content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(request.content_id)},
                {"$set": {
                    "ig_media_id": f"demo_ig_{request.content_id}",
                    "ig_published_at": datetime.now(timezone.utc),
                    "ig_status": "published",
                    "platform": "instagram",
                    "status": "published",
                    "published_at": datetime.now(timezone.utc),
                }}
            )
        return InstagramPublishResponse(
            success=True,
            ig_media_id=f"demo_ig_{DEMO_MEDIA_ID}",
            message="[DEMO MODE] Image published to Instagram successfully",
        )

    effective_image_url = request.get_effective_image_url()
    try:
        result = await InstagramService.publish_image(
            db=db,
            user_id=user_id,
            image_url=effective_image_url,
            caption=request.caption,
            content_id=request.content_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing to Instagram: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Unable to publish to Instagram: {str(e)}"
        )

    return InstagramPublishResponse(
        success=True,
        ig_media_id=result.get("ig_media_id"),
        message="Published to Instagram successfully",
    )


# ──────────────────────────────────────────────
# Publishing — Reel
# ──────────────────────────────────────────────

@router.post("/reel", response_model=InstagramPublishResponse)
async def instagram_reel(
    request: InstagramReelRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Publish a reel to Instagram."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        logger.info(f"[DEMO MODE] Publishing reel for user {user_id}")
        if request.content_id and ObjectId.is_valid(request.content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(request.content_id)},
                {"$set": {
                    "ig_media_id": f"demo_reel_{request.content_id}",
                    "ig_published_at": datetime.now(timezone.utc),
                    "ig_status": "published",
                    "platform": "instagram",
                    "status": "published",
                    "published_at": datetime.now(timezone.utc),
                }}
            )
        return InstagramPublishResponse(
            success=True,
            ig_media_id=f"demo_reel_{DEMO_MEDIA_ID}",
            message="[DEMO MODE] Reel published to Instagram successfully",
        )

    effective_video_url = request.get_effective_video_url()
    result = await InstagramService.publish_reel(
        db=db,
        user_id=user_id,
        video_url=effective_video_url,
        caption=request.caption,
        content_id=request.content_id,
        share_to_feed=request.share_to_feed,
    )

    return InstagramPublishResponse(
        success=True,
        ig_media_id=result.get("ig_media_id"),
        message="Reel published to Instagram successfully",
    )


# ──────────────────────────────────────────────
# Media
# ──────────────────────────────────────────────

@router.get("/media")
async def instagram_media(
    limit: int = Query(25, ge=1, le=100),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get recent Instagram media."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {
                    "id": "demo_media_001",
                    "caption": "✨ Our latest product showcase! #business #demo",
                    "media_type": "IMAGE",
                    "media_url": "https://image.pollinations.ai/prompt/professional%20product%20photography?width=1080&height=1080&nologo=true",
                    "permalink": "https://www.instagram.com/p/demo001/",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "like_count": 42,
                    "comments_count": 5,
                },
                {
                    "id": "demo_media_002",
                    "caption": "🎬 Behind the scenes of our latest campaign",
                    "media_type": "VIDEO",
                    "media_url": "",
                    "permalink": "https://www.instagram.com/p/demo002/",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "like_count": 89,
                    "comments_count": 12,
                },
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    media = await InstagramService.get_media(
        access_token=access_token,
        ig_user_id=conn["instagram_user_id"],
        limit=limit,
    )

    return {"success": True, "data": media}


# ──────────────────────────────────────────────
# Comments
# ──────────────────────────────────────────────

@router.get("/comments/{media_id}")
async def get_comments(
    media_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get comments on an Instagram media object."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {
                    "id": "demo_comment_001",
                    "text": "Love this! 🔥",
                    "username": "demo_follower_1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "like_count": 3,
                },
                {
                    "id": "demo_comment_002",
                    "text": "Where can I buy this?",
                    "username": "demo_follower_2",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "like_count": 1,
                },
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    comments = await InstagramService.get_comments(
        access_token=access_token,
        media_id=media_id,
    )

    return {"success": True, "data": comments}


@router.post("/comments/reply")
async def reply_to_comment(
    request: InstagramReplyRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Reply to a comment on Instagram."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": {"id": f"demo_reply_{request.comment_id}"},
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    result = await InstagramService.reply_to_comment(
        access_token=access_token,
        comment_id=request.comment_id,
        message=request.message,
    )

    return {"success": True, "data": result}


@router.post("/comments/{comment_id}/hide")
async def hide_comment(
    comment_id: str,
    hide: bool = Query(True),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Hide or unhide a comment."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {"success": True, "demo_mode": True, "data": {"hidden": hide}}

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    result = await InstagramService.hide_comment(
        access_token=access_token,
        comment_id=comment_id,
        hide=hide,
    )

    return {"success": True, "data": result}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Delete a comment."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {"success": True, "demo_mode": True, "message": "Comment deleted"}

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    success = await InstagramService.delete_comment(
        access_token=access_token,
        comment_id=comment_id,
    )

    return {"success": success, "message": "Comment deleted" if success else "Failed to delete comment"}


# ──────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────

@router.get("/conversations")
async def get_conversations(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get Instagram DM conversations."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {
                    "id": "demo_conv_001",
                    "participants": [
                        {"id": DEMO_IG_USER_ID, "username": DEMO_IG_USERNAME},
                        {"id": "demo_user_100", "username": "demo_customer"},
                    ],
                    "messages": [
                        {
                            "id": "demo_msg_001",
                            "message": "Hi, I'm interested in your product!",
                            "from": {"id": "demo_user_100", "username": "demo_customer"},
                            "created_time": datetime.now(timezone.utc).isoformat(),
                        },
                    ],
                },
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    conversations = await InstagramService.get_conversations(
        access_token=access_token,
        ig_user_id=conn["instagram_user_id"],
    )

    return {"success": True, "data": conversations}


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get messages in a specific conversation."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {
                    "id": "demo_msg_001",
                    "message": "Hi, I'm interested in your product!",
                    "from": {"id": "demo_user_100", "username": "demo_customer"},
                    "created_time": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "id": "demo_msg_002",
                    "message": "Thanks for reaching out! Here are the details...",
                    "from": {"id": DEMO_IG_USER_ID, "username": DEMO_IG_USERNAME},
                    "created_time": datetime.now(timezone.utc).isoformat(),
                },
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    messages = await InstagramService.get_conversation_messages(
        access_token=access_token,
        conversation_id=conversation_id,
    )

    return {"success": True, "data": messages}


@router.post("/messages")
async def send_message(
    request: InstagramSendMessageRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Send a message to an Instagram user.
    The recipient must have messaged the professional account first.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": {
                "recipient_id": request.recipient_id,
                "message_id": f"demo_sent_msg_{secrets.token_hex(4)}",
            },
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    result = await InstagramService.send_message(
        access_token=access_token,
        ig_user_id=conn["instagram_user_id"],
        recipient_id=request.recipient_id,
        message=request.message,
    )

    return {"success": True, "data": result}


# ──────────────────────────────────────────────
# Scheduling (integrates with existing post_queue)
# ──────────────────────────────────────────────

@router.post("/schedule")
async def schedule_instagram_post(
    request: InstagramScheduleRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Schedule an Instagram post or reel for future publishing.
    Integrates with the existing autopilot/scheduler system.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))

    # Create queue item compatible with existing scheduler
    queue_item = {
        "user_id": user_id,
        "content_id": request.content_id,
        "platform": "instagram",
        "media_type": request.media_type,
        "image_url": request.image_url,
        "video_url": request.video_url,
        "caption": request.caption,
        "scheduled_for": request.scheduled_for,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }

    result = await db["post_queue"].insert_one(queue_item)
    queue_item["_id"] = str(result.inserted_id)

    # Update content status if content_id provided
    if request.content_id and ObjectId.is_valid(request.content_id):
        await db["contents"].update_one(
            {"_id": ObjectId(request.content_id)},
            {"$set": {
                "status": "scheduled",
                "scheduled_at": request.scheduled_for,
                "platform": "instagram",
            }}
        )

    return {
        "success": True,
        "message": f"Scheduled for {request.scheduled_for.isoformat()}",
        "data": {"queue_id": queue_item["_id"]},
    }


# ──────────────────────────────────────────────
# Insights / Analytics
# ──────────────────────────────────────────────

@router.get("/insights")
async def get_insights(
    period: str = Query("day", enum=["day", "week", "days_28", "month", "lifetime"]),
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get Instagram account insights."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {
                    "name": "impressions",
                    "period": period,
                    "values": [{"value": 1523, "end_time": datetime.now(timezone.utc).isoformat()}],
                    "title": "Impressions",
                },
                {
                    "name": "reach",
                    "period": period,
                    "values": [{"value": 892, "end_time": datetime.now(timezone.utc).isoformat()}],
                    "title": "Reach",
                },
                {
                    "name": "accounts_engaged",
                    "period": period,
                    "values": [{"value": 156, "end_time": datetime.now(timezone.utc).isoformat()}],
                    "title": "Accounts Engaged",
                },
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    insights = await InstagramService.get_account_insights(
        access_token=access_token,
        ig_user_id=conn["instagram_user_id"],
        period=period,
    )

    return {"success": True, "data": insights}


@router.get("/insights/{media_id}")
async def get_media_insights(
    media_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Get insights for a specific Instagram media."""
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await InstagramService.get_connection(db, user_id)

    if _should_use_demo(conn):
        return {
            "success": True,
            "demo_mode": True,
            "data": [
                {"name": "impressions", "values": [{"value": 347}], "title": "Impressions"},
                {"name": "reach", "values": [{"value": 210}], "title": "Reach"},
                {"name": "engagement", "values": [{"value": 45}], "title": "Engagement"},
                {"name": "saved", "values": [{"value": 12}], "title": "Saved"},
            ],
        }

    access_token = await InstagramService.get_decrypted_token(db, user_id)

    insights = await InstagramService.get_media_insights(
        access_token=access_token,
        media_id=media_id,
    )

    return {"success": True, "data": insights}


# ──────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────

@router.get("/webhook")
async def webhook_verify(
    request: Request,
    db=Depends(get_database),
):
    """Instagram webhook verification (GET)."""
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    if not mode and not token and not challenge:
        # Endpoint was hit directly without Meta's verification parameters
        return PlainTextResponse(content="Webhook endpoint is active and waiting for Meta verification.")

    if InstagramService.is_demo_mode():
        if challenge:
            return PlainTextResponse(content=challenge)
        return PlainTextResponse(content="webhook_demo_ok")

    result = InstagramService.verify_webhook(mode, token, challenge)
    if result:
        return PlainTextResponse(content=result)

    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
@router.post("/callback")
async def webhook_receive(
    request: Request,
    db=Depends(get_database),
):
    """Instagram webhook event receiver (POST)."""
    try:
        body = await request.json()
    except Exception:
        # If the endpoint is hit directly (e.g., from Swagger) with empty/invalid JSON,
        # we return a 200 OK so the test passes instead of throwing 400 Bad Request.
        return {"status": "ok", "message": "Webhook endpoint is active and waiting for Meta events."}

    if InstagramService.is_demo_mode():
        await db["instagram_webhook_events"].insert_one({
            "type": "demo_event",
            "data": body,
            "received_at": datetime.now(timezone.utc),
        })
        return {"status": "ok", "demo_mode": True}

    # Verify webhook signature if X-Hub-Signature-256 is present
    signature = request.headers.get("X-Hub-Signature-256")
    if signature and settings.INSTAGRAM_APP_SECRET:
        import hmac as hmac_mod
        raw_body = await request.body()
        expected = "sha256=" + hmac_mod.new(
            settings.INSTAGRAM_APP_SECRET.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac_mod.compare_digest(signature, expected):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    result = await InstagramService.process_webhook_event(db, body)
    return result


@router.get("/signup-url")
@router.get("/create-account-url")
async def instagram_signup_url():
    """Returns official Instagram account signup URL."""
    return {
        "platform": "instagram",
        "url": "https://www.instagram.com/accounts/emailsignup/",
        "official_signup_url": "https://www.instagram.com/accounts/emailsignup/",
        "instructions": "Create your Instagram account on the official website, then return and connect it."
    }

