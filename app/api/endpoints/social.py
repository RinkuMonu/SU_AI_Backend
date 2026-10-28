from fastapi import APIRouter, Depends, HTTPException, Body, status
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.social_service import SocialService
from app.services.social_connectivity_service import (
    get_social_onboarding_status,
    get_all_platform_connections,
    disconnect_social_platform,
    skip_social_connectivity,
    CREATE_ACCOUNT_URLS,
)
from app.schemas.social import (
    SocialOnboardingStatusResponse,
    SocialDisconnectResponse,
    CreateAccountUrlsResponse,
)

router = APIRouter(
    prefix="/api/v1/social",
    tags=["Social"]
)


# ─────────────────────────────────────────────────────────────
# Social Media Connectivity Onboarding Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/onboarding-status", response_model=SocialOnboardingStatusResponse, operation_id="social_get_onboarding_status")
@router.get("/status", response_model=SocialOnboardingStatusResponse, operation_id="social_get_status_alias")
async def get_social_media_onboarding_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Returns the Social Media Connectivity onboarding status for the authenticated user.
    Rules:
    - Businessman who completed Brand Kit and has 0 connected accounts: should_show_modal=True.
    - Businessman with at least 1 verified connected account: should_show_modal=False, social_connectivity_completed=True.
    - Businessman who hasn't finished Brand Kit yet: should_show_modal=False (Brand Kit takes precedence).
    - Influencer/Creator: should_show_modal=False, social_connectivity_completed=True.
    """
    return await get_social_onboarding_status(db, current_user)


@router.get("/platforms", operation_id="social_get_platforms_status")
async def get_platforms_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Retrieves status for all supported social platforms (Instagram, Facebook, LinkedIn).
    Never exposes raw tokens, secrets, or encrypted credentials.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    platforms = await get_all_platform_connections(db, user_id)
    return {
        "success": True,
        "platforms": platforms,
        "create_account_urls": CREATE_ACCOUNT_URLS,
    }


@router.get("/create-account-urls", response_model=CreateAccountUrlsResponse, operation_id="social_create_account_urls")
@router.get("/create-account", response_model=CreateAccountUrlsResponse, operation_id="social_create_account_alias")
@router.get("/signup-urls", response_model=CreateAccountUrlsResponse, operation_id="social_signup_urls_alias")
@router.get("/register-urls", response_model=CreateAccountUrlsResponse, operation_id="social_register_urls_alias")
async def get_create_account_urls():
    """
    Returns official signup URLs for supported platforms and guidance instructions.
    Used when the user clicks 'Create Account' in the onboarding popup.
    """
    return CreateAccountUrlsResponse()


@router.post("/disconnect/{platform}", response_model=SocialDisconnectResponse, operation_id="social_disconnect_platform")
async def disconnect_platform(
    platform: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Disconnects a specified social account (instagram, facebook, or linkedin).
    Recalculates onboarding status: if 0 accounts remain, social_connectivity_completed becomes False.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    success, is_completed, should_show = await disconnect_social_platform(db, user_id, platform)

    return SocialDisconnectResponse(
        success=success,
        platform=platform.lower(),
        message=f"{platform.capitalize()} disconnected successfully",
        social_connectivity_completed=is_completed,
        should_show_modal=should_show,
    )


@router.post("/skip", operation_id="social_skip_onboarding")
@router.post("/onboarding/skip", operation_id="social_skip_onboarding_alias")
async def skip_social_onboarding(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Skips the Social Media Connectivity onboarding step without marking it completed.
    Stops the popup from reopening on refresh.
    """
    user_id = str(current_user.get("id") or current_user.get("_id"))
    await skip_social_connectivity(db, user_id)
    return {
        "success": True,
        "message": "Social media connectivity skipped successfully",
        "social_connectivity_completed": False,
        "social_connectivity_skipped": True,
        "should_show_modal": False,
    }


# ─────────────────────────────────────────────────────────────
# Social Publishing Endpoints (Preserved Functionality)
# ─────────────────────────────────────────────────────────────

@router.post("/publish-instagram/{content_id}")
async def publish_instagram(
    content_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user.get("id") or current_user.get("_id")
    business_id = str(business_id)
    
    result = await SocialService.publish_to_instagram(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    return {"success": True, "message": "Successfully published to Instagram", "data": result}


@router.post("/publish-facebook/{content_id}")
async def publish_facebook(
    content_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user.get("id") or current_user.get("_id")
    business_id = str(business_id)
    
    result = await SocialService.publish_to_facebook(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    return {"success": True, "message": "Successfully published to Facebook", "data": result}


@router.post("/publish-linkedin/{content_id}")
async def publish_linkedin(
    content_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user.get("id") or current_user.get("_id")
    business_id = str(business_id)
    
    result = await SocialService.publish_to_linkedin(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    return {"success": True, "message": "Successfully published to LinkedIn", "data": result}


@router.post("/publish-linkedin")
async def publish_linkedin_direct(
    req: dict = Body(default={}),
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    user_id = str(current_user.get("id") or current_user.get("_id"))
    caption = req.get("caption", "")
    image_url = req.get("image_url")
    content_id = req.get("content_id")
    business_id = current_user.get("business_id")
    
    from app.services.linkedin_service import LinkedInService
    result = await LinkedInService.publish_post(
        db=db,
        user_id=user_id,
        caption=caption,
        image_url=image_url,
        content_id=content_id,
        business_id=business_id,
    )
    return {"success": True, "message": "Successfully published to LinkedIn", "data": result}


# ─────────────────────────────────────────────────────────────
# Unified Social Connect & Status Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/connect/{platform}", operation_id="social_connect_platform")
@router.get("/{platform}/connect", operation_id="social_connect_platform_alias")
async def connect_platform(
    platform: str,
    frontend_url: str | None = None,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Unified route to initiate OAuth connect for any supported platform (instagram, facebook, linkedin).
    """
    platform_lower = platform.lower().strip()
    if platform_lower == "instagram":
        from app.api.endpoints.instagram import instagram_connect
        return await instagram_connect(frontend_url=frontend_url, current_user=current_user, db=db)
    elif platform_lower == "facebook":
        from app.api.endpoints.facebook import facebook_connect
        return await facebook_connect(frontend_url=frontend_url, current_user=current_user, db=db)
    elif platform_lower == "linkedin":
        from app.api.endpoints.linkedin import linkedin_connect
        return await linkedin_connect(current_user=current_user, db=db)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported social platform '{platform}'. Supported: instagram, facebook, linkedin"
        )


@router.get("/status/{platform}", operation_id="social_platform_status")
@router.get("/{platform}/status", operation_id="social_platform_status_alias")
async def get_single_platform_status(
    platform: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Unified route to retrieve connection and configuration status for a specific platform.
    """
    platform_lower = platform.lower().strip()
    if platform_lower == "instagram":
        from app.api.endpoints.instagram import instagram_status
        return await instagram_status(current_user=current_user, db=db)
    elif platform_lower == "facebook":
        from app.api.endpoints.facebook import facebook_status
        return await facebook_status(current_user=current_user, db=db)
    elif platform_lower == "linkedin":
        from app.api.endpoints.linkedin import linkedin_status
        return await linkedin_status(current_user=current_user, db=db)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported social platform '{platform}'. Supported: instagram, facebook, linkedin"
        )


# Alias router for /api/social
api_social_router = APIRouter(prefix="/api/social", tags=["Social"])
api_social_router.add_api_route("/onboarding-status", get_social_media_onboarding_status, methods=["GET"], response_model=SocialOnboardingStatusResponse)
api_social_router.add_api_route("/status", get_social_media_onboarding_status, methods=["GET"], response_model=SocialOnboardingStatusResponse)
api_social_router.add_api_route("/platforms", get_platforms_status, methods=["GET"])
api_social_router.add_api_route("/create-account-urls", get_create_account_urls, methods=["GET"], response_model=CreateAccountUrlsResponse)
api_social_router.add_api_route("/create-account", get_create_account_urls, methods=["GET"], response_model=CreateAccountUrlsResponse)
api_social_router.add_api_route("/signup-urls", get_create_account_urls, methods=["GET"], response_model=CreateAccountUrlsResponse)
api_social_router.add_api_route("/disconnect/{platform}", disconnect_platform, methods=["POST"], response_model=SocialDisconnectResponse)
api_social_router.add_api_route("/connect/{platform}", connect_platform, methods=["GET"])
api_social_router.add_api_route("/{platform}/connect", connect_platform, methods=["GET"])
api_social_router.add_api_route("/status/{platform}", get_single_platform_status, methods=["GET"])
api_social_router.add_api_route("/{platform}/status", get_single_platform_status, methods=["GET"])

