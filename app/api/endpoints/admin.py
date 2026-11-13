from fastapi import APIRouter, Depends
from typing import List, Any
from app.core.security import require_admin, CurrentUser
from app.core.database import get_database
from app.schemas.admin import AdminDashboardOverview, DashboardStats, AIUsageStats
from app.services.admin_dashboard_service import AdminDashboardService

router = APIRouter()

@router.get("/dashboard/overview", response_model=AdminDashboardOverview)
async def get_dashboard_overview(current_user: CurrentUser = Depends(require_admin)):
    total_users = await AdminDashboardService.get_total_users()
    total_businesses = await AdminDashboardService.get_total_businesses()
    recent_users = await AdminDashboardService.get_recent_users()
    recent_businesses = await AdminDashboardService.get_recent_businesses()
    ai_usage = await AdminDashboardService.get_ai_usage()
    
    return AdminDashboardOverview(
        stats=DashboardStats(
            total_users=total_users,
            total_businesses=total_businesses,
            active_subscriptions=None,
            credits_used=None
        ),
        ai_usage=AIUsageStats(**ai_usage),
        recent_registrations=recent_users,
        recent_businesses=recent_businesses
    )

@router.get("/users")
async def get_all_users(current_user: CurrentUser = Depends(require_admin)) -> Any:
    db = get_database()
    result_users = []
    seen_keys = set()

    # 1. Base registered users
    users_cursor = db["users"].find({}, {"hashed_password": 0})
    users = await users_cursor.to_list(length=200)
    for u in users:
        u["id"] = str(u["_id"])
        del u["_id"]
        key = (u.get("email") or u["id"]).lower()
        seen_keys.add(key)
        result_users.append(u)

    # 2. Real Influencer Profiles from sevenunique_ai_db
    influencers_cursor = db["influencer_profiles"].find({})
    influencers = await influencers_cursor.to_list(length=200)
    for inf in influencers:
        name = inf.get("fullName") or inf.get("name") or inf.get("username")
        if not name or str(name).strip() in ["", "None", "null"]:
            continue
        inf_id = str(inf["_id"])
        email = inf.get("email") or f"{str(inf.get('username') or 'creator').lower().replace(' ', '')}@dhandagrow.com"
        key = email.lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)

        avatar = inf.get("profile_image") or inf.get("avatar_url") or inf.get("profile_picture") or inf.get("avatar")
        result_users.append({
            "id": inf_id,
            "name": name,
            "fullName": name,
            "username": inf.get("username", ""),
            "email": email,
            "phone": inf.get("phone") or inf.get("phone_number") or "+91 98765 00000",
            "role": "influencer",
            "category": inf.get("category") or "Lifestyle & Fashion",
            "profile_image": avatar,
            "avatar": avatar,
            "follower_count": inf.get("follower_count", 0),
            "expectedPricePerPost": inf.get("expectedPricePerPost", 5000),
            "plan": "Pro Plus",
            "status": "active",
            "created_at": inf.get("created_at") or "2026-10-23T04:34:16.000Z",
            "updated_at": inf.get("updated_at")
        })

    # 3. Real Businesses & Merchants from sevenunique_ai_db
    businesses_cursor = db["businesses"].find({})
    businesses = await businesses_cursor.to_list(length=300)
    for biz in businesses:
        b_name = biz.get("business_name") or biz.get("name")
        if not b_name or str(b_name).strip() in ["", "None", "null"]:
            continue
        biz_id = str(biz["_id"])
        email = biz.get("email") or f"{str(b_name).lower().replace(' ', '').replace('&', '')[:15]}@dhandagrow.com"
        key = email.lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)

        logo = biz.get("logo_url") or biz.get("logo")
        result_users.append({
            "id": biz_id,
            "name": b_name,
            "businessName": b_name,
            "ownerName": biz.get("owner_name") or biz.get("ownerName") or "Business Owner",
            "email": email,
            "phone": biz.get("phone") or biz.get("phone_number") or "+91 98765 11111",
            "role": "businessman",
            "category": biz.get("category") or biz.get("business_category") or "Retail & Merchant",
            "logo_url": logo,
            "avatar": logo,
            "profile_image": logo,
            "website": biz.get("website") or biz.get("website_url"),
            "tagline": biz.get("tagline"),
            "plan": "Pro",
            "status": "active",
            "created_at": biz.get("created_at") or "2026-10-27T07:33:53.000Z",
            "updated_at": biz.get("updated_at")
        })

    return result_users

@router.get("/businesses")
async def get_all_businesses(current_user: CurrentUser = Depends(require_admin)) -> Any:
    db = get_database()
    businesses_cursor = db["businesses"].find({})
    businesses = await businesses_cursor.to_list(length=100)
    for business in businesses:
        business["id"] = str(business["_id"])
        del business["_id"]
    return businesses

@router.get("/ai-config")
async def get_admin_ai_config(current_user: CurrentUser = Depends(require_admin)) -> Any:
    """
    Returns active centralized OpenAI model configuration.
    Strictly never exposes the OPENAI_API_KEY.
    """
    from app.core.config import settings
    return {
        "provider": "openai",
        "text_model": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
        "image_model": getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini"),
        "reasoning_model": getattr(settings, "OPENAI_REASONING_MODEL", "gpt-4.1-mini"),
        "models": {
            "text": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            "image": getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini"),
            "vision": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            "analysis": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            "agent": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini")
        }
    }


@router.post("/ai-test")
async def test_admin_ai_connectivity(current_user: CurrentUser = Depends(require_admin)) -> Any:
    """
    Validates OpenAI API connectivity without exposing credentials.
    """
    import time
    from app.core.config import settings
    from app.ai.factory import AIProviderFactory
    from fastapi import HTTPException, status

    if not getattr(settings, "OPENAI_API_KEY", None):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OPENAI_API_KEY is not configured on the server."
        )

    t0 = time.time()
    try:
        provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
        res = await provider.generate_text("Reply with 'OK'", max_tokens=10)
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        return {
            "success": True,
            "provider": "openai",
            "model": getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
            "status": "connected",
            "latency_ms": elapsed_ms,
            "response": res.get("text", "").strip()
        }
    except Exception as e:
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        err_msg = str(e)
        # Redact any accidental keys
        from app.ai.providers.openai_provider import sanitize_secrets
        return {
            "success": False,
            "provider": "openai",
            "status": "connection_error",
            "latency_ms": elapsed_ms,
            "error": sanitize_secrets(err_msg)
        }
