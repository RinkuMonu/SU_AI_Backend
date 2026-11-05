import urllib.parse
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
from app.schemas.influencer_social import (
    SocialConnectInitRequest,
    SocialConnectInitResponse,
    SocialPlatformConnectionInfo,
    InfluencerSocialStatusResponse,
    SocialCallbackExchangeRequest,
    SocialCallbackResponse,
    SocialDisconnectResponse,
    DismissSocialPromptResponse,
)
from app.services.influencer_social_service import InfluencerSocialService

router = APIRouter(tags=["Influencer Social Connections"])


def _extract_user_id(current_user: dict) -> str:
    uid = current_user.get("id") or current_user.get("_id") or current_user.get("user_id")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials."
        )
    return str(uid)


# ---------------------------------------------------------------------------
# 1. Connection Status & Prompt State
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    response_model=InfluencerSocialStatusResponse,
    summary="Get Influencer Social Connection Status",
    description="Retrieve connection and verification status across all supported platforms (Instagram, Facebook, LinkedIn), including first-visit prompt dismissal state."
)
@router.get(
    "",
    response_model=InfluencerSocialStatusResponse,
    include_in_schema=False,
)
async def get_influencer_social_status(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    return await InfluencerSocialService.get_social_status(db, user_id)


# ---------------------------------------------------------------------------
# 2. Initiate OAuth Connection
# ---------------------------------------------------------------------------

@router.post(
    "/connect/{platform}",
    response_model=SocialConnectInitResponse,
    summary="Initiate Social Platform Connection",
    description="Generate official OAuth authorization URL and CSRF state token for supported platform ('instagram', 'facebook', 'linkedin')."
)
async def connect_platform(
    platform: str,
    payload: Optional[SocialConnectInitRequest] = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    frontend_url = payload.frontend_url if payload else None
    rerequest = payload.rerequest if payload else False
    return await InfluencerSocialService.initiate_connection(
        db=db,
        user_id=user_id,
        platform=platform,
        frontend_url=frontend_url,
        rerequest=rerequest,
    )


# ---------------------------------------------------------------------------
# 3. OAuth Callbacks (Browser Redirect & Direct API)
# ---------------------------------------------------------------------------

@router.get(
    "/callback/{platform}",
    summary="OAuth Provider Callback Redirect",
    description="Browser redirect endpoint called by OAuth providers (Meta/LinkedIn). Validates code, verifies account ownership, and redirects to frontend."
)
async def oauth_callback_redirect(
    platform: str,
    code: Optional[str] = Query(None, description="Authorization code from provider"),
    state: Optional[str] = Query(None, description="CSRF state token"),
    error: Optional[str] = Query(None, description="Error code if user declined"),
    error_description: Optional[str] = Query(None, description="Detailed error description"),
    db=Depends(get_database),
):
    # Lookup state doc to find frontend return URL
    effective_frontend = "http://localhost:3000/influencer/social-accounts"
    if state:
        state_doc = await db["influencer_social_oauth_states"].find_one({"state": state})
        if state_doc and state_doc.get("frontend_url"):
            effective_frontend = state_doc["frontend_url"]

    sep = "&" if "?" in effective_frontend else "?"

    try:
        res = await InfluencerSocialService.handle_oauth_callback(
            db=db,
            platform=platform,
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        return RedirectResponse(
            url=f"{effective_frontend}{sep}social_connected=true&platform={platform}&username={urllib.parse.quote(res.platform_username or '')}"
        )
    except HTTPException as e:
        err_msg = urllib.parse.quote(str(e.detail))
        return RedirectResponse(url=f"{effective_frontend}{sep}social_error={err_msg}&platform={platform}")
    except Exception as e:
        err_msg = urllib.parse.quote(str(e))
        return RedirectResponse(url=f"{effective_frontend}{sep}social_error={err_msg}&platform={platform}")


@router.post(
    "/callback/{platform}",
    response_model=SocialCallbackResponse,
    summary="Direct OAuth Code Exchange",
    description="Direct JSON endpoint to exchange authorization code for verified social account connection (SPA / mobile / testing)."
)
async def oauth_callback_json(
    platform: str,
    payload: SocialCallbackExchangeRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    return await InfluencerSocialService.handle_oauth_callback(
        db=db,
        platform=platform,
        code=payload.code,
        state=payload.state,
        user_id_override=user_id,
    )


# ---------------------------------------------------------------------------
# 4. Disconnect & Reconnect
# ---------------------------------------------------------------------------

@router.post(
    "/disconnect/{platform}",
    response_model=SocialDisconnectResponse,
    summary="Disconnect Social Platform",
    description="Disconnect a linked social account, revoke stored tokens, and update profile state without modifying other onboarding fields."
)
async def disconnect_platform(
    platform: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    return await InfluencerSocialService.disconnect_platform(db=db, user_id=user_id, platform=platform)


@router.post(
    "/reconnect/{platform}",
    response_model=SocialConnectInitResponse,
    summary="Reconnect / Re-authenticate Social Platform",
    description="Re-initiates OAuth authorization flow for an account that is disconnected or expired."
)
async def reconnect_platform(
    platform: str,
    payload: Optional[SocialConnectInitRequest] = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    frontend_url = payload.frontend_url if payload else None
    return await InfluencerSocialService.initiate_connection(
        db=db,
        user_id=user_id,
        platform=platform,
        frontend_url=frontend_url,
        rerequest=True,
    )


# ---------------------------------------------------------------------------
# 5. Dismiss Post-Onboarding Prompt
# ---------------------------------------------------------------------------

@router.post(
    "/dismiss-prompt",
    response_model=DismissSocialPromptResponse,
    summary="Dismiss Post-Onboarding Social Connection Prompt",
    description="Records that the influencer dismissed the social account connection modal so it does not reopen on future dashboard visits."
)
async def dismiss_prompt(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _extract_user_id(current_user)
    return await InfluencerSocialService.dismiss_prompt(db=db, user_id=user_id)
