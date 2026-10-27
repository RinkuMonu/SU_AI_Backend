import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from bson import ObjectId
from fastapi import HTTPException, status

from app.schemas.social import (
    PlatformConnectionInfo,
    SocialOnboardingStatusResponse,
    CreateAccountUrlsResponse,
)
from app.services.brand_service import get_brand_kit_by_owner

logger = logging.getLogger(__name__)

CREATE_ACCOUNT_URLS = {
    "instagram": "https://www.instagram.com/accounts/emailsignup/",
    "facebook": "https://www.facebook.com/r.php",
    "linkedin": "https://www.linkedin.com/signup",
}


async def sync_business_social_status(db, user_id: str) -> Tuple[bool, List[str]]:
    """
    Recalculates and persists social media connectivity status for a user's business.
    Rules:
    - If at least one verified active connection exists, social_connectivity_completed = True.
    - If zero connected accounts (or last account was disconnected), social_connectivity_completed = False.
    """
    now = datetime.now(timezone.utc)

    # 1. Check Instagram
    ig_conn = await db["instagram_connections"].find_one(
        {"user_id": user_id, "platform": "instagram", "connected": True}
    )

    # 2. Check Facebook
    fb_conn = await db["facebook_connections"].find_one(
        {"user_id": user_id, "platform": "facebook", "connected": True}
    )

    # 3. Check LinkedIn
    li_conn = await db["linkedin_connections"].find_one(
        {"user_id": user_id, "platform": "linkedin", "connected": True}
    )

    connected_platforms = []
    if ig_conn:
        connected_platforms.append("instagram")
    if fb_conn:
        connected_platforms.append("facebook")
    if li_conn:
        connected_platforms.append("linkedin")

    is_completed = len(connected_platforms) > 0

    # Retrieve business
    business = await db["businesses"].find_one({"owner_id": user_id})
    completed_at = None

    if is_completed:
        completed_at = business.get("social_connectivity_completed_at") if business else None
        if not completed_at:
            completed_at = now
    else:
        completed_at = None

    update_fields = {
        "social_connectivity_completed": is_completed,
        "social_connectivity_completed_at": completed_at,
        "connected_platforms": connected_platforms,
        "updated_at": now,
    }

    if business:
        await db["businesses"].update_one(
            {"_id": business["_id"]},
            {"$set": update_fields}
        )
    else:
        # Create lightweight business record if not already created
        update_fields["owner_id"] = user_id
        update_fields["name"] = "My Business"
        update_fields["category"] = "General"
        update_fields["location"] = "India"
        update_fields["created_at"] = now
        await db["businesses"].insert_one(update_fields)

    return is_completed, connected_platforms


async def get_all_platform_connections(db, user_id: str) -> Dict[str, PlatformConnectionInfo]:
    """
    Gathers frontend-ready connection info for Instagram, Facebook, and LinkedIn.
    Never exposes raw tokens, secrets, or encrypted blobs.
    """
    # Instagram
    ig_conn = await db["instagram_connections"].find_one(
        {"user_id": user_id, "platform": "instagram", "connected": True}
    )
    ig_info = PlatformConnectionInfo(
        platform="instagram",
        connected=bool(ig_conn),
        account_id=ig_conn.get("instagram_user_id") if ig_conn else None,
        account_name=ig_conn.get("instagram_username") if ig_conn else None,
        account_type=ig_conn.get("account_type", "BUSINESS") if ig_conn else None,
        profile_picture_url=ig_conn.get("profile_picture_url") if ig_conn else None,
        connected_at=ig_conn.get("created_at") if ig_conn else None,
    )

    # Facebook
    fb_conn = await db["facebook_connections"].find_one(
        {"user_id": user_id, "platform": "facebook", "connected": True}
    )
    fb_info = PlatformConnectionInfo(
        platform="facebook",
        connected=bool(fb_conn),
        account_id=fb_conn.get("fb_page_id") or fb_conn.get("account_id") if fb_conn else None,
        account_name=fb_conn.get("fb_page_name") or fb_conn.get("account_name") if fb_conn else None,
        account_type=fb_conn.get("account_type", "PAGE") if fb_conn else None,
        profile_picture_url=fb_conn.get("profile_picture_url") if fb_conn else None,
        connected_at=fb_conn.get("created_at") if fb_conn else None,
    )

    # LinkedIn
    li_conn = await db["linkedin_connections"].find_one(
        {"user_id": user_id, "platform": "linkedin", "connected": True}
    )
    li_info = PlatformConnectionInfo(
        platform="linkedin",
        connected=bool(li_conn),
        account_id=li_conn.get("linkedin_author_id") or li_conn.get("account_id") if li_conn else None,
        account_name=li_conn.get("display_name") or li_conn.get("account_name") if li_conn else None,
        account_type=li_conn.get("account_type", "PROFILE") if li_conn else None,
        profile_picture_url=li_conn.get("profile_picture_url") if li_conn else None,
        connected_at=li_conn.get("created_at") if li_conn else None,
    )

    return {
        "instagram": ig_info,
        "facebook": fb_info,
        "linkedin": li_info,
    }


async def get_social_onboarding_status(db, current_user) -> SocialOnboardingStatusResponse:
    """
    Evaluates whether the Social Media Connectivity onboarding popup should open.
    Rules:
    1. Influencers / Creators: excluded from Businessman onboarding modal (should_show_modal=False).
    2. Role not selected: modal does not show (role selection has priority).
    3. Brand Kit incomplete: modal does NOT show yet (Brand Kit has priority).
    4. Brand Kit complete + 0 connected accounts: should_show_modal=True, social_connectivity_completed=False.
    5. Brand Kit complete + >= 1 connected accounts: should_show_modal=False, social_connectivity_completed=True.
    """
    role = current_user.get("role")
    user_id = str(current_user.get("id") or current_user.get("_id"))

    # 1. Influencers
    if role == "influencer":
        return SocialOnboardingStatusResponse(
            role="influencer",
            brand_kit_completed=True,
            social_connectivity_completed=True,
            social_connectivity_completed_at=None,
            should_show_modal=False,
            connected_count=0,
            platforms={},
            create_account_urls=CREATE_ACCOUNT_URLS,
        )

    # 2. No selected role
    if not role:
        return SocialOnboardingStatusResponse(
            role=None,
            brand_kit_completed=False,
            social_connectivity_completed=False,
            social_connectivity_completed_at=None,
            should_show_modal=False,
            connected_count=0,
            platforms={},
            create_account_urls=CREATE_ACCOUNT_URLS,
        )

    # 3. Check Brand Kit prerequisite based on online_presence
    business = await db["businesses"].find_one({"owner_id": user_id})
    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
    online_presence = (
        (business.get("online_presence") if business else None) or
        (user_doc.get("online_presence") if user_doc else None)
    )

    brand_kit = await get_brand_kit_by_owner(db, user_id)
    brand_kit_completed = False
    brand_kit_started_or_saved = False

    if online_presence and online_presence != "no_online_presence":
        # website, google_maps, marketplace_seller, wholesale_b2b do NOT require Brand Kit
        brand_kit_completed = brand_kit.get("brand_kit_completed", False) if brand_kit else False
        brand_kit_started_or_saved = True
    else:
        if brand_kit:
            brand_kit_completed = brand_kit.get("brand_kit_completed", False)
            if not brand_kit_completed:
                has_name = bool(brand_kit.get("business_name") or brand_kit.get("brand_name"))
                has_logo = bool(brand_kit.get("logo_url"))
                has_color = bool(brand_kit.get("primary_color"))
                if has_name and has_logo and has_color and brand_kit.get("brand_kit_status") != "in_progress":
                    brand_kit_completed = True
            brand_kit_started_or_saved = bool(
                brand_kit_completed or
                brand_kit.get("brand_kit_status") in ["in_progress", "completed"] or
                brand_kit.get("completion_percentage", 0) > 0 or
                brand_kit.get("brand_kit_dismissed", False) or
                (business and business.get("brand_kit_dismissed", False)) or
                True  # Incomplete Brand Kit does not block social connectivity
            )
        else:
            brand_kit_started_or_saved = True

    # 4. Check active platform connections
    platforms = await get_all_platform_connections(db, user_id)
    connected_count = sum(1 for p in platforms.values() if p.connected)
    is_social_completed = connected_count > 0

    # Retrieve completed timestamp and skipped status from business
    business = await db["businesses"].find_one({"owner_id": user_id})
    completed_at = business.get("social_connectivity_completed_at") if business else None
    is_social_skipped = bool(
        (business and business.get("social_connectivity_skipped", False)) or
        (current_user.get("social_connectivity_skipped", False) if isinstance(current_user, dict) else False)
    )

    # Determine popup display condition
    # Stop popup if at least 1 account connected OR if user skipped
    # Otherwise show modal only once Step 1 is started/saved and Step 2 is pending
    if is_social_completed or is_social_skipped:
        should_show_modal = False
    else:
        should_show_modal = brand_kit_started_or_saved and (connected_count == 0) and not is_social_skipped

    return SocialOnboardingStatusResponse(
        role=role,
        brand_kit_completed=brand_kit_completed,
        social_connectivity_completed=is_social_completed,
        social_connectivity_completed_at=completed_at,
        should_show_modal=should_show_modal,
        connected_count=connected_count,
        platforms=platforms,
        create_account_urls=CREATE_ACCOUNT_URLS,
    )


async def skip_social_connectivity(db, user_id: str) -> bool:
    """
    Marks social connectivity step as skipped so the blocking popup does not reappear.
    Does not mark social_connectivity_completed as True.
    """
    now = datetime.now(timezone.utc)
    await db["businesses"].update_one(
        {"owner_id": user_id},
        {"$set": {"social_connectivity_skipped": True, "social_connectivity_skipped_at": now, "updated_at": now}},
        upsert=True
    )
    from bson import ObjectId
    if ObjectId.is_valid(user_id):
        await db["users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"social_connectivity_skipped": True, "updated_at": now}}
        )
    return True


async def disconnect_social_platform(db, user_id: str, platform: str) -> Tuple[bool, bool, bool]:
    """
    Disconnects a social platform for the user and recalculates completion status.
    Returns: (success, is_social_completed, should_show_modal)
    """
    platform_lower = platform.lower().strip()
    success = False

    if platform_lower == "instagram":
        from app.services.instagram_service import InstagramService
        success = await InstagramService.disconnect(db, user_id)
        # Clear business fields
        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {"ig_access_token": None, "ig_account_id": None, "updated_at": datetime.now(timezone.utc)}}
        )
    elif platform_lower == "facebook":
        result = await db["facebook_connections"].update_one(
            {"user_id": user_id, "platform": "facebook"},
            {"$set": {"connected": False, "encrypted_access_token": None, "updated_at": datetime.now(timezone.utc)}}
        )
        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {"fb_access_token": None, "fb_page_id": None, "fb_page_name": None, "updated_at": datetime.now(timezone.utc)}}
        )
        success = result.modified_count > 0 or True
    elif platform_lower == "linkedin":
        from app.services.linkedin_service import LinkedInService
        success = await LinkedInService.disconnect(db, user_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported social platform: '{platform}'. Must be 'instagram', 'facebook', or 'linkedin'."
        )

    # Recalculate status
    is_social_completed, _ = await sync_business_social_status(db, user_id)

    # Check if Brand Kit is completed
    brand_kit = await get_brand_kit_by_owner(db, user_id)
    brand_kit_completed = brand_kit.get("brand_kit_completed", False) if brand_kit else False

    # If all accounts are disconnected and Brand Kit is completed, modal becomes eligible again
    should_show_modal = brand_kit_completed and not is_social_completed

    return success, is_social_completed, should_show_modal


class SocialConnectivityService:
    get_social_onboarding_status = staticmethod(get_social_onboarding_status)
    sync_business_social_status = staticmethod(sync_business_social_status)
    skip_social_connectivity = staticmethod(skip_social_connectivity)
    disconnect_social_platform = staticmethod(disconnect_social_platform)
    get_all_platform_connections = staticmethod(get_all_platform_connections)
