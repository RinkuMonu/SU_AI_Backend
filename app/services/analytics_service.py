"""
Analytics service — queries REAL MongoDB data from EXISTING collections.

No new collections are created.  Every query is scoped to the
authenticated user (via ``user_id`` or ``business_id``).

Data-source map
===============
Collection             | Metric                  | Scope Field
-----------------------|-------------------------|---------------------
contents               | Posts (type=social_post) | user_id  (str)
reel_jobs              | Reels                   | user_id  (ObjectId)
ai_generations         | Captions / Images       | user_id  (str)
photoshoots            | Photoshoot generations  | user_id  (str)
credit_transactions    | Credits used            | user_id  (str)
products               | Product catalogue       | business_id (ObjectId)
calendars              | Calendar plans          | user_id  (str)

Double-count prevention
=======================
Each metric pulls from exactly ONE authoritative collection:
  • posts       → contents (type="social_post")
  • reels       → reel_jobs
  • images      → ai_generations (generation_type="image")
  • photoshoots → photoshoots
  • captions    → ai_generations (generation_type="caption")
Photoshoots are also mirrored in ``contents``, but we count from
``photoshoots`` only so there is zero double-counting.

Marketing Score (deterministic, 0–100)
======================================
    content_activity  = min(posts_in_range * 5, 25)
    ai_usage          = min(total_generations_in_range * 2, 25)
    product_catalogue = min(current_product_count * 5, 20)
    reel_activity     = min(reels_in_range * 5, 15)
    score             = min(sum, 100)

This score reflects INTERNAL platform activity only.
It does NOT represent Instagram/Facebook/WhatsApp performance.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from app.services.social_analytics_service import SocialAnalyticsService

logger = logging.getLogger(__name__)

VALID_RANGES = {"7d": 7, "30d": 30, "90d": 90}


class AnalyticsService:
    """Reads real analytics from existing MongoDB collections."""

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_overview(
        self,
        user_id: str,
        business_id: Optional[str],
        range_param: str,
    ) -> dict:
        """
        Build the complete analytics overview for a single user.

        Parameters
        ----------
        user_id : str
            The ``_id`` of the authenticated user (as a string).
        business_id : str | None
            The ``_id`` of the user's business (may be None).
        range_param : str
            One of ``"7d"``, ``"30d"``, ``"90d"``.
        """
        days = VALID_RANGES[range_param]
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = today_start - timedelta(days=days - 1)

        reel_filter = self._reel_user_filter(user_id)

        # ── Content analytics (date-filtered) ────────────────────────
        posts = await self._count(
            "contents",
            {"user_id": user_id, "type": "social_post",
             "created_at": {"$gte": start_date}},
        )
        reels = await self._count(
            "reel_jobs",
            {**reel_filter, "created_at": {"$gte": start_date}},
        )
        images = await self._count(
            "ai_generations",
            {"user_id": user_id, "generation_type": "image",
             "created_at": {"$gte": start_date}},
        )
        photoshoots = await self._count(
            "photoshoots",
            {"user_id": user_id, "created_at": {"$gte": start_date}},
        )
        captions = await self._count(
            "ai_generations",
            {"user_id": user_id, "generation_type": "caption",
             "created_at": {"$gte": start_date}},
        )

        content = {
            "posts": posts,
            "reels": reels,
            "images": images,
            "photoshoots": photoshoots,
            "captions": captions,
        }

        # ── AI usage (date-filtered) ─────────────────────────────────
        total_generations = posts + reels + images + photoshoots + captions
        credits_used = await self._sum_credits_used(user_id, start_date)

        ai_usage = {
            "total_generations": total_generations,
            "post_generations": posts,
            "image_generations": images,
            "photoshoot_generations": photoshoots,
            "reel_generations": reels,
            "credits_used": credits_used,
        }

        # ── Business analytics ───────────────────────────────────────
        # Product count = current catalogue (NOT date-filtered).
        product_count = 0
        if business_id and ObjectId.is_valid(business_id):
            product_count = await self._count(
                "products",
                {"business_id": ObjectId(business_id)},
            )

        business = {"products": product_count}

        # ── Daily activity buckets ───────────────────────────────────
        activity = await self._daily_activity(
            user_id, reel_filter, start_date, days,
        )

        # ── External metrics (real API or smart estimation) ───────────
        social_svc = SocialAnalyticsService(self.db)
        external = await social_svc.get_external_metrics(
            business_id=business_id,
            user_id=user_id,
            days=days,
        )

        # ── Marketing score ──────────────────────────────────────────
        marketing_score = self._marketing_score(
            posts, reels, total_generations, product_count,
        )

        # ── Recommendation ───────────────────────────────────────────
        recommendation = self._recommendation(
            posts, reels, images, photoshoots, captions,
            product_count,
        )

        return {
            "range": range_param,
            "period": {
                "start": start_date.isoformat(),
                "end": now.isoformat(),
            },
            "content": content,
            "ai_usage": ai_usage,
            "business": business,
            "activity": activity,
            "external": external,
            "marketing_score": marketing_score,
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reel_user_filter(user_id: str) -> dict:
        """
        reel_service stores ``user_id`` as ``ObjectId`` when the value
        is a valid ObjectId string.  We query with ``$or`` to match both
        representations safely.
        """
        if ObjectId.is_valid(user_id):
            return {
                "$or": [
                    {"user_id": user_id},
                    {"user_id": ObjectId(user_id)},
                ],
            }
        return {"user_id": user_id}

    async def _count(self, collection: str, query: dict) -> int:
        """Safe count_documents wrapper — returns 0 on any error."""
        try:
            return await self.db[collection].count_documents(query)
        except Exception as exc:
            logger.error("analytics._count(%s) failed: %s", collection, exc)
            return 0

    async def _sum_credits_used(
        self, user_id: str, start_date: datetime,
    ) -> int:
        """
        Sum *actual* credit usage: deductions only (credits < 0),
        excluding refund transactions (action ending with ``_refund``).

        Refunds have positive ``credits`` AND an action suffix of
        ``_refund``.  Filtering on ``credits < 0`` already excludes
        refunds, but the regex guard is an extra safety net.
        """
        try:
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "created_at": {"$gte": start_date},
                        "credits": {"$lt": 0},
                        "action": {"$not": {"$regex": "_refund$"}},
                    },
                },
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": {"$abs": "$credits"}},
                    },
                },
            ]
            results = await self.db["credit_transactions"].aggregate(
                pipeline,
            ).to_list(length=1)
            return results[0]["total"] if results else 0
        except Exception as exc:
            logger.error("analytics._sum_credits_used failed: %s", exc)
            return 0

    async def _daily_activity(
        self,
        user_id: str,
        reel_filter: dict,
        start_date: datetime,
        days: int,
    ) -> list:
        """
        Returns one bucket per calendar day (UTC) in the selected range.
        Zero-activity days have explicit zeroes — they are never omitted.
        """
        # All dates in range  ─────────────────────────────────────────
        all_dates = [
            (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        ]

        # Per-day aggregations from each source ───────────────────────
        posts_by_day = await self._agg_by_day(
            "contents",
            {"user_id": user_id, "type": "social_post",
             "created_at": {"$gte": start_date}},
        )
        reels_by_day = await self._agg_by_day(
            "reel_jobs",
            {**reel_filter, "created_at": {"$gte": start_date}},
        )
        captions_by_day = await self._agg_by_day(
            "ai_generations",
            {"user_id": user_id, "generation_type": "caption",
             "created_at": {"$gte": start_date}},
        )
        images_by_day = await self._agg_by_day(
            "ai_generations",
            {"user_id": user_id, "generation_type": "image",
             "created_at": {"$gte": start_date}},
        )
        photoshoots_by_day = await self._agg_by_day(
            "photoshoots",
            {"user_id": user_id, "created_at": {"$gte": start_date}},
        )

        # Merge into daily buckets ────────────────────────────────────
        buckets = []
        for date_str in all_dates:
            p = posts_by_day.get(date_str, 0)
            r = reels_by_day.get(date_str, 0)
            ai = (
                p
                + r
                + captions_by_day.get(date_str, 0)
                + images_by_day.get(date_str, 0)
                + photoshoots_by_day.get(date_str, 0)
            )
            buckets.append({
                "date": date_str,
                "posts": p,
                "reels": r,
                "ai_generations": ai,
            })
        return buckets

    async def _agg_by_day(
        self, collection: str, query: dict,
    ) -> dict:
        """
        Returns ``{date_string: count}`` via a MongoDB aggregation that
        groups documents by their ``created_at`` calendar day (UTC).
        """
        try:
            pipeline = [
                {"$match": query},
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$created_at",
                            },
                        },
                        "count": {"$sum": 1},
                    },
                },
            ]
            result: dict[str, int] = {}
            async for doc in self.db[collection].aggregate(pipeline):
                if doc["_id"] is not None:
                    result[doc["_id"]] = doc["count"]
            return result
        except Exception as exc:
            logger.error(
                "analytics._agg_by_day(%s) failed: %s", collection, exc,
            )
            return {}

    # ------------------------------------------------------------------
    # Marketing score
    # ------------------------------------------------------------------

    @staticmethod
    def _marketing_score(
        posts: int,
        reels: int,
        total_generations: int,
        products: int,
    ) -> dict:
        """
        Deterministic 0–100 score from REAL internal data.

        NOT external social-media performance.

        Formula:
            content_activity  = min(posts_in_range * 5, 25)
            ai_usage          = min(total_generations_in_range * 2, 25)
            product_catalogue = min(current_product_count * 5, 20)
            reel_activity     = min(reels_in_range * 5, 15)
            score             = min(sum, 100)
        """
        content_activity = min(posts * 5, 25)
        ai_usage_pts = min(total_generations * 2, 25)
        product_catalogue = min(products * 5, 20)
        reel_activity = min(reels * 5, 15)

        raw = (
            content_activity
            + ai_usage_pts
            + product_catalogue
            + reel_activity
        )
        score = min(raw, 100)

        return {
            "score": score,
            "breakdown": {
                "content_activity": content_activity,
                "ai_usage": ai_usage_pts,
                "product_catalogue": product_catalogue,
                "reel_activity": reel_activity,
            },
            "formula": (
                "content_activity = min(posts_in_range * 5, 25); "
                "ai_usage = min(total_generations_in_range * 2, 25); "
                "product_catalogue = min(current_product_count * 5, 20); "
                "reel_activity = min(reels_in_range * 5, 15); "
                "score = min(sum, 100)"
            ),
        }

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    @staticmethod
    def _recommendation(
        posts: int,
        reels: int,
        images: int,
        photoshoots: int,
        captions: int,
        products: int,
    ) -> dict:
        """
        Deterministic, data-driven recommendation.

        Checks gaps in priority order and returns the first applicable
        recommendation.  Different users will receive different
        recommendations based on their actual data.
        """
        if products == 0:
            return {
                "text": (
                    "Start by adding products to your catalogue. "
                    "A complete product catalogue is the foundation "
                    "for all AI-generated content."
                ),
                "type": "products",
            }

        if posts == 0 and captions == 0:
            return {
                "text": (
                    "You haven't created any posts or captions yet. "
                    "Try generating your first social media post to "
                    "kickstart your content strategy."
                ),
                "type": "content",
            }

        if reels == 0:
            return {
                "text": (
                    "Reels are one of the most engaging content formats. "
                    "Try creating your first AI-generated reel to boost "
                    "audience engagement."
                ),
                "type": "reels",
            }



        if photoshoots == 0:
            return {
                "text": (
                    "Elevate your product visuals with AI photoshoots. "
                    "Professional product imagery significantly improves "
                    "engagement and conversions."
                ),
                "type": "photoshoots",
            }

        if images == 0:
            return {
                "text": (
                    "Try generating custom AI images to make your content "
                    "stand out with unique, eye-catching visuals."
                ),
                "type": "images",
            }

        if posts < 5:
            return {
                "text": (
                    f"You've created {posts} post(s) this period. "
                    "Aim for at least 5 posts to maintain a consistent "
                    "social media presence."
                ),
                "type": "content",
            }

        if reels < 3:
            return {
                "text": (
                    f"You've created {reels} reel(s) this period. "
                    "Creating more reels can significantly boost your "
                    "reach and engagement."
                ),
                "type": "reels",
            }

        return {
            "text": (
                "Great work! You're actively using the platform. "
                "Keep up the momentum and explore new content formats "
                "to maximise your marketing reach."
            ),
            "type": "general",
        }
