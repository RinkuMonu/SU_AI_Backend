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
    users_cursor = db["users"].find({}, {"hashed_password": 0})
    users = await users_cursor.to_list(length=100)
    # Convert ObjectId to string for JSON serialization
    for user in users:
        user["id"] = str(user["_id"])
        del user["_id"]
    return users

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
