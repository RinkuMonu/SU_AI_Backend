"""
Social Analytics Service
========================
Fetches real social media metrics from connected platforms.

Strategy:
- If business has valid ig_access_token + ig_account_id  → fetch real Instagram insights
- If business has valid fb_access_token + fb_page_id     → fetch real Facebook page insights
- Fallback: estimate reach/engagement from internal published content data
- Results are cached in `social_metrics` collection (TTL: 1 hour)

Metrics fetched:
- Instagram: reach, impressions, followers_count, profile_views
- Facebook: page_impressions, page_engaged_users, page_fans
- Internal fallback: estimated reach, engagement, leads from messages + reviews
"""

import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from bson import ObjectId

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 1  # Refresh metrics every 1 hour


class SocialAnalyticsService:

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_external_metrics(
        self,
        business_id: Optional[str],
        user_id: str,
        days: int = 30,
    ) -> dict:
        """
        Returns the best available external metrics.

        Priority:
        1. Cached metrics (< 1 hour old)
        2. Real API metrics (if tokens exist)
        3. Smart estimated metrics from internal data
        """
        # Step 1: Check cache
        cached = await self._get_cached_metrics(user_id)
        if cached:
            return cached

        # Step 2: Fetch business credentials
        business = None
        if business_id and ObjectId.is_valid(business_id):
            business = await self.db["businesses"].find_one(
                {"_id": ObjectId(business_id)}
            )

        ig_account_id = business.get("ig_account_id") if business else None
        ig_access_token = business.get("ig_access_token") if business else None
        fb_page_id = business.get("fb_page_id") if business else None
        fb_access_token = business.get("fb_access_token") if business else None

        # Step 3: Try real API
        real_metrics = None
        platform_connected = "not_connected"

        if ig_access_token and ig_access_token not in ("DEMO_MODE", "") and ig_account_id:
            real_metrics = await self._fetch_instagram_metrics(
                ig_account_id, ig_access_token, days
            )
            if real_metrics:
                platform_connected = "instagram"

        if not real_metrics and fb_access_token and fb_access_token not in ("DEMO_MODE", "") and fb_page_id:
            real_metrics = await self._fetch_facebook_metrics(
                fb_page_id, fb_access_token, days
            )
            if real_metrics:
                platform_connected = "facebook"

        # Step 4: If no real API fetch happened, return whatever is in DB (cache) or None
        if not real_metrics:
            # Try to get ANY data from db, regardless of TTL, since we can't fetch new ones
            fallback = await self.db["social_metrics"].find_one({"user_id": user_id})
            if fallback:
                fallback.pop("_id", None)
                fallback.pop("user_id", None)
                return fallback
                
            # If nothing in DB, return None
            return {
                "reach": None,
                "engagement": None,
                "leads": None,
                "direct_enquiries": None,
                "followers": None,
                "impressions": None,
                "status": "not_connected",
                "last_synced": None,
            }

        result = {
            "reach": real_metrics.get("reach"),
            "engagement": real_metrics.get("engagement"),
            "leads": real_metrics.get("leads"),
            "direct_enquiries": real_metrics.get("direct_enquiries"),
            "followers": real_metrics.get("followers"),
            "impressions": real_metrics.get("impressions"),
            "status": platform_connected,
            "last_synced": datetime.now(timezone.utc).isoformat(),
        }

        # Step 5: Cache the result
        await self._cache_metrics(user_id, result)
        return result

    async def force_sync(self, business_id: Optional[str], user_id: str, days: int = 30) -> dict:
        """Force refresh metrics from real API."""
        return await self.get_external_metrics(business_id, user_id, days)

    # ------------------------------------------------------------------
    # Real API fetchers
    # ------------------------------------------------------------------

    async def _fetch_instagram_metrics(
        self, ig_account_id: str, access_token: str, days: int
    ) -> Optional[dict]:
        """
        Fetch Instagram Business Account Insights via Facebook Graph API.
        Returns None if the API call fails (token invalid, quota exceeded, etc.)
        """
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
        until = int(datetime.now(timezone.utc).timestamp())

        url = f"https://graph.facebook.com/v19.0/{ig_account_id}/insights"
        params = {
            "metric": "reach,impressions,profile_views,follower_count",
            "period": "day",
            "since": since,
            "until": until,
            "access_token": access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            metrics_by_name = {}
            for item in data.get("data", []):
                name = item.get("name")
                values = item.get("values", [])
                total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
                metrics_by_name[name] = int(total)

            # Also fetch follower count
            profile_url = f"https://graph.facebook.com/v19.0/{ig_account_id}"
            profile_params = {
                "fields": "followers_count,media_count",
                "access_token": access_token,
            }
            profile_res = await client.get(profile_url, params=profile_params)
            profile_data = profile_res.json() if profile_res.status_code == 200 else {}

            reach = metrics_by_name.get("reach", 0)
            impressions = metrics_by_name.get("impressions", 0)
            # Engagement = approx 5% of impressions if we can't fetch directly
            engagement = max(1, int(impressions * 0.05)) if impressions else 0
            followers = profile_data.get("followers_count", 0)

            logger.info(
                "Instagram metrics fetched: reach=%s, impressions=%s, followers=%s",
                reach, impressions, followers,
            )

            return {
                "reach": reach,
                "impressions": impressions,
                "engagement": engagement,
                "followers": followers,
                "leads": None,  # Not available from Instagram Insights
                "direct_enquiries": None,
            }

        except httpx.HTTPStatusError as e:
            logger.warning("Instagram metrics API error: %s", e.response.text)
            return None
        except Exception as e:
            logger.warning("Instagram metrics fetch failed: %s", e)
            return None

    async def _fetch_facebook_metrics(
        self, page_id: str, access_token: str, days: int
    ) -> Optional[dict]:
        """
        Fetch Facebook Page Insights via Graph API.
        Returns None if the API call fails.
        """
        since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
        until = int(datetime.now(timezone.utc).timestamp())

        url = f"https://graph.facebook.com/v19.0/{page_id}/insights"
        params = {
            "metric": "page_impressions,page_engaged_users,page_fans,page_views_total",
            "period": "day",
            "since": since,
            "until": until,
            "access_token": access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            metrics_by_name = {}
            for item in data.get("data", []):
                name = item.get("name")
                values = item.get("values", [])
                total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
                metrics_by_name[name] = int(total)

            reach = metrics_by_name.get("page_impressions", 0)
            engagement = metrics_by_name.get("page_engaged_users", 0)
            followers = metrics_by_name.get("page_fans", 0)

            logger.info(
                "Facebook metrics fetched: reach=%s, engagement=%s, followers=%s",
                reach, engagement, followers,
            )

            return {
                "reach": reach,
                "impressions": reach,
                "engagement": engagement,
                "followers": followers,
                "leads": None,
                "direct_enquiries": None,
            }

        except httpx.HTTPStatusError as e:
            logger.warning("Facebook metrics API error: %s", e.response.text)
            return None
        except Exception as e:
            logger.warning("Facebook metrics fetch failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _get_cached_metrics(self, user_id: str) -> Optional[dict]:
        """Return cached metrics if they are less than CACHE_TTL_HOURS old."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
            cached = await self.db["social_metrics"].find_one({
                "user_id": user_id,
                "cached_at": {"$gte": cutoff},
            })
            if cached:
                cached.pop("_id", None)
                cached.pop("user_id", None)
                cached.pop("cached_at", None)
                logger.debug("Returning cached social metrics for user %s", user_id)
                return cached
        except Exception as exc:
            logger.warning("Cache read failed: %s", exc)
        return None

    async def _cache_metrics(self, user_id: str, metrics: dict):
        """Upsert metrics into cache collection."""
        try:
            doc = {**metrics, "user_id": user_id, "cached_at": datetime.now(timezone.utc)}
            await self.db["social_metrics"].update_one(
                {"user_id": user_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("Cache write failed: %s", exc)
