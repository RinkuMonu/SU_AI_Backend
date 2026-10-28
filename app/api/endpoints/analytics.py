"""
Analytics API endpoint.

GET /api/v1/analytics/overview?range=7d|30d|90d

Returns a comprehensive analytics overview for the authenticated user,
sourced entirely from real MongoDB data.  External metrics return null
because the required social integrations are not implemented.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_database
from app.core.security import get_current_user
from app.api.dependencies import require_feature
from app.services.analytics_service import AnalyticsService, VALID_RANGES
from app.services.social_analytics_service import SocialAnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/overview")
async def get_analytics_overview(
    date_range: str = Query(
        "30d",
        alias="range",
        description="Date range filter: 7d, 30d, or 90d",
    ),
    current_user=Depends(get_current_user),
):
    """
    Authenticated analytics overview.

    Supported ranges: ``7d``, ``30d``, ``90d``.
    Invalid values return HTTP 400.

    All data comes from real MongoDB records scoped to the
    authenticated user.  Empty collections and missing businesses
    return valid zero/null responses — the API never crashes.
    """
    # ── Validate range ───────────────────────────────────────────────
    if date_range not in VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid range '{date_range}'. "
                f"Must be one of: {', '.join(sorted(VALID_RANGES.keys()))}"
            ),
        )

    # ── Build analytics ──────────────────────────────────────────────
    try:
        db = get_database()
        service = AnalyticsService(db)
        # CurrentUser is a dict subclass — both .get() and attribute access are safe
        user_id = str(current_user.get("id") or current_user.id)
        business_id = current_user.get("business_id")
        result = await service.get_overview(
            user_id=user_id,
            business_id=business_id,
            range_param=date_range,
        )
        return {"success": True, "data": result}
    except HTTPException:
        raise  # Re-raise known HTTP errors
    except Exception as exc:
        logger.error(
            "Analytics overview failed for user %s: %s",
            current_user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve analytics. Please try again later.",
        )


@router.post("/social-sync")
async def sync_social_metrics(
    current_user=Depends(get_current_user),
):
    """
    Force-refresh social media metrics from real APIs (Instagram / Facebook).

    - Clears the 1-hour cache and fetches fresh data.
    - If the business has valid social tokens, real API data is returned.
    - Otherwise, metrics are estimated from internal platform activity.

    Returns:
        The latest external metrics with a ``last_synced`` timestamp.
    """
    try:
        db = get_database()
        user_id = str(current_user.get("id") or current_user.id)
        business_id = current_user.get("business_id")

        social_svc = SocialAnalyticsService(db)
        metrics = await social_svc.force_sync(
            business_id=business_id,
            user_id=user_id,
        )
        return {"success": True, "data": metrics}
    except Exception as exc:
        logger.error("Social sync failed for user %s: %s", current_user.get("id"), exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to sync social metrics. Please try again later.",
        )


@router.post("/visual-forecast", dependencies=[Depends(require_feature("analytics"))])
async def get_visual_forecast(
    request: dict = None,
    range_param: str = Query("30d", alias="range"),
    current_user=Depends(get_current_user),
):
    """
    Generate predictive visual marketing health gauges & forecast powered by Gemini API.
    """
    try:
        db = get_database()
        service = AnalyticsService(db)
        user_id = str(current_user.get("id") or current_user.id)
        business_id = current_user.get("business_id")

        range_days = 30
        if range_param == "7d":
            range_days = 7
        elif range_param == "90d":
            range_days = 90

        analytics_data = (request or {}).get("data") if request else {}
        if not analytics_data:
            analytics_data = await service.get_overview(
                user_id=user_id,
                business_id=business_id,
                range_param=range_param,
            )

        forecast_data = await service.generate_visual_forecast(analytics_data, range_days)
        return {"success": True, "data": forecast_data}
    except Exception as exc:
        logger.error("Visual forecast failed for user %s: %s", current_user.get("id"), exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate visual forecast.",
        )
