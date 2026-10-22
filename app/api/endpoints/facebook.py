import secrets
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
import httpx

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.services.social_connectivity_service import sync_business_social_status
from app.services.instagram_service import encrypt_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])

DEMO_FB_PAGE_ID = "109876543210987"
DEMO_FB_PAGE_NAME = "Demo Business Page"


def _is_fb_demo_mode() -> bool:
    app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
    app_secret = getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "INSTAGRAM_APP_SECRET", None)
    return not app_id or not app_secret


@router.get("/connect")
async def facebook_connect(current_user=Depends(get_current_user), db=Depends(get_database)):
    """
    Initiate Facebook OAuth flow.
    Generates CSRF state and returns authorization URL.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    state = secrets.token_urlsafe(32)
    await db["facebook_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    })

    if _is_fb_demo_mode():
        logger.info(f"[DEMO MODE] Facebook connect initiated for user {user_id}")
        return {
            "authorization_url": f"http://localhost:8000/api/facebook/callback?code=demo_fb_code&state={state}"
        }

    app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
    redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")
    scopes = "pages_show_list,pages_read_engagement,pages_manage_posts"
    auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
    )

    return {"authorization_url": auth_url}


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
    Exchanges authorization code for token, fetches page identity,
    persists encrypted connection, and synchronizes onboarding status.
    """
    frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()

    if error:
        logger.warning(f"Facebook OAuth error: {error} - {error_description}")
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={error_description or error}")

    if not code or not state:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=missing_code_or_state")

    # Verify and consume state
    oauth_state = await db["facebook_oauth_states"].find_one_and_delete({"state": state})
    if not oauth_state:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=invalid_state")

    user_id = oauth_state["user_id"]
    now = datetime.now(timezone.utc)

    # Demo Mode handling
    if _is_fb_demo_mode():
        logger.info(f"[DEMO MODE] Facebook callback for user {user_id}")
        demo_connection = {
            "user_id": user_id,
            "platform": "facebook",
            "fb_page_id": DEMO_FB_PAGE_ID,
            "account_id": DEMO_FB_PAGE_ID,
            "fb_page_name": DEMO_FB_PAGE_NAME,
            "account_name": DEMO_FB_PAGE_NAME,
            "account_type": "PAGE",
            "encrypted_access_token": encrypt_token("DEMO_FB_TOKEN"),
            "connected": True,
            "created_at": now,
            "updated_at": now,
        }
        await db["facebook_connections"].update_one(
            {"user_id": user_id, "platform": "facebook"},
            {"$set": demo_connection},
            upsert=True
        )

        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "fb_page_id": DEMO_FB_PAGE_ID,
                "fb_access_token": "DEMO_FB_TOKEN",
                "fb_page_name": DEMO_FB_PAGE_NAME,
                "updated_at": now
            }},
            upsert=True
        )

        # Sync onboarding completion
        await sync_business_social_status(db, user_id)

        # Secure redirect without leaking access tokens
        return RedirectResponse(
            url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true"
        )

    app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
    app_secret = getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "INSTAGRAM_APP_SECRET", None)
    redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")

    # Exchange code for token
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
        params = {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code
        }
        res = await client.get(token_url, params=params)
        if res.status_code != 200:
            logger.error(f"Facebook token exchange failed: {res.text}")
            return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=token_exchange_failed")

        data = res.json()
        user_access_token = data.get("access_token")

        # Fetch Pages managed by this user
        page_id = None
        page_name = None
        page_token = user_access_token

        try:
            pages_res = await client.get(
                "https://graph.facebook.com/v19.0/me/accounts",
                params={"access_token": user_access_token, "fields": "id,name,access_token"}
            )
            if pages_res.status_code == 200:
                pages_data = pages_res.json().get("data", [])
                if pages_data:
                    first_page = pages_data[0]
                    page_id = first_page.get("id")
                    page_name = first_page.get("name")
                    page_token = first_page.get("access_token", user_access_token)
        except Exception as e:
            logger.warning(f"Could not fetch Facebook pages: {e}")

        if not page_id:
            # Fallback to user profile
            try:
                me_res = await client.get(
                    "https://graph.facebook.com/v19.0/me",
                    params={"access_token": user_access_token, "fields": "id,name"}
                )
                if me_res.status_code == 200:
                    me_data = me_res.json()
                    page_id = me_data.get("id")
                    page_name = me_data.get("name")
            except Exception as e:
                logger.warning(f"Could not fetch Facebook profile: {e}")

        page_id = page_id or "fb_unknown_id"
        page_name = page_name or "Facebook Business"

        # Persist connection with encrypted token
        encrypted = encrypt_token(page_token)
        connection_doc = {
            "user_id": user_id,
            "platform": "facebook",
            "fb_page_id": page_id,
            "account_id": page_id,
            "fb_page_name": page_name,
            "account_name": page_name,
            "account_type": "PAGE",
            "encrypted_access_token": encrypted,
            "connected": True,
            "created_at": now,
            "updated_at": now,
        }
        await db["facebook_connections"].update_one(
            {"user_id": user_id, "platform": "facebook"},
            {"$set": connection_doc},
            upsert=True
        )

        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "fb_page_id": page_id,
                "fb_access_token": page_token,
                "fb_page_name": page_name,
                "updated_at": now
            }},
            upsert=True
        )

        # Sync onboarding completion
        await sync_business_social_status(db, user_id)

    # Secure redirect without leaking access tokens
    return RedirectResponse(
        url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true"
    )


@router.get("/status")
async def facebook_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Check Facebook connection status.
    Never exposes raw tokens, secrets, or encrypted blobs.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    conn = await db["facebook_connections"].find_one(
        {"user_id": user_id, "platform": "facebook", "connected": True}
    )

    if conn:
        return {
            "connected": True,
            "platform": "facebook",
            "account_id": conn.get("fb_page_id") or conn.get("account_id"),
            "display_name": conn.get("fb_page_name") or conn.get("account_name"),
            "account_type": conn.get("account_type", "PAGE"),
            "profile_picture_url": conn.get("profile_picture_url"),
        }

    return {
        "connected": False,
        "platform": "facebook",
        "account_id": None,
        "display_name": None,
    }


@router.post("/disconnect")
async def facebook_disconnect(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Disconnect Facebook account and update onboarding status.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    now = datetime.now(timezone.utc)

    result = await db["facebook_connections"].update_one(
        {"user_id": user_id, "platform": "facebook"},
        {"$set": {
            "connected": False,
            "encrypted_access_token": None,
            "updated_at": now
        }}
    )

    await db["businesses"].update_one(
        {"owner_id": user_id},
        {"$set": {
            "fb_access_token": None,
            "fb_page_id": None,
            "fb_page_name": None,
            "updated_at": now
        }}
    )

    is_social_completed, _ = await sync_business_social_status(db, user_id)

    return {
        "success": True,
        "message": "Facebook disconnected successfully",
        "platform": "facebook",
        "social_connectivity_completed": is_social_completed,
    }


@router.get("/signup-url")
@router.get("/create-account-url")
async def facebook_signup_url():
    """Returns official Facebook account/page signup URL."""
    return {
        "platform": "facebook",
        "url": "https://www.facebook.com/r.php",
        "official_signup_url": "https://www.facebook.com/r.php",
        "instructions": "Create your Facebook account or Page on the official website, then return and connect it."
    }

