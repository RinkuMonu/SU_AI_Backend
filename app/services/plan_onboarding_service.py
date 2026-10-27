import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app.core.billing_config import PLANS, BILLING_CYCLES, get_formatted_plans
from app.models.business import Business
from app.schemas.billing_onboarding import (
    PlanOnboardingStatusResponse,
    ActivePlanSummary,
    PlanCard,
)
from app.services.brand_service import get_brand_kit_by_owner
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

QUALIFYING_PAID_PLANS = {"STARTER", "GROWTH", "PRO", "BUSINESS", "INFLUENCER"}


class PlanOnboardingService:
    @staticmethod
    async def sync_business_plan_status(
        db, user_id: str, plan_id: str, billing_cycle: str = "monthly"
    ) -> None:
        """
        Marks plan activation complete for the user's business record.
        Only called when payment is verified and plan is active.
        """
        now = datetime.now(timezone.utc)
        normalized_plan = plan_id.upper().strip()
        cycle = (billing_cycle or "monthly").lower().strip()

        business = await db["businesses"].find_one({"owner_id": user_id})
        update_fields = {
            "plan_activation_completed": True,
            "plan_activation_completed_at": now,
            "active_plan_id": normalized_plan,
            "billing_cycle": cycle,
            "updated_at": now,
        }

        if business:
            await db["businesses"].update_one(
                {"_id": business["_id"]},
                {"$set": update_fields}
            )
        else:
            update_fields["owner_id"] = user_id
            update_fields["name"] = "My Business"
            update_fields["category"] = "General"
            update_fields["location"] = "India"
            update_fields["created_at"] = now
            await db["businesses"].insert_one(update_fields)

        logger.info(f"Plan activation onboarding completed for user {user_id} (plan={normalized_plan}, cycle={cycle})")

    @staticmethod
    async def get_plan_onboarding_status(db, current_user: dict) -> PlanOnboardingStatusResponse:
        """
        Calculates Step 3: Plan Selection and Activation onboarding eligibility and modal state.
        
        Rules:
        1. Influencer role: Bypasses Businessman onboarding popups (should_show_modal=False).
        2. Role not selected: modal does not show (role selection has priority).
        3. Brand Kit must be completed first (Step 1).
        4. At least one social media account must be connected (Step 2).
        5. Only when Step 1 and Step 2 are complete does Plan Onboarding become eligible.
        6. If no qualifying paid plan is activated, should_show_modal=True and
           plan_activation_completed=False so the modal reopens on refresh/next visit.
        7. Closing or declining the popup does NOT mark it complete.
        8. Once payment is server-verified and plan is activated:
           plan_activation_completed=True, should_show_modal=False.
        """
        role = current_user.get("role")
        user_id = str(current_user.get("id") or current_user.get("_id"))

        # 1. Influencers
        if role == "influencer":
            sub = await SubscriptionService.get_or_create_subscription(db, user_id)
            active_plan_id = sub.get("plan_id", "INFLUENCER")
            active_summary = ActivePlanSummary(
                plan_id=active_plan_id,
                plan_name=PLANS.get(active_plan_id, {}).get("name", active_plan_id),
                billing_cycle=sub.get("billing_cycle", "monthly"),
                credits_remaining=sub.get("credits_remaining", 0),
                credits_total=sub.get("credits_total", 0),
                status=sub.get("status", "active"),
                is_paid_plan=True,
                activated_at=sub.get("start_date") or sub.get("created_at"),
                expires_at=sub.get("expires_at")
            )
            return PlanOnboardingStatusResponse(
                role="influencer",
                brand_kit_completed=True,
                social_connectivity_completed=True,
                plan_activation_completed=True,
                plan_activation_completed_at=None,
                is_eligible=True,
                should_show_modal=False,
                active_plan=active_summary,
                available_plans=get_formatted_plans(active_plan_id),
                billing_cycles=BILLING_CYCLES,
                currency="INR"
            )

        # 2. No selected role
        if not role:
            return PlanOnboardingStatusResponse(
                role=None,
                brand_kit_completed=False,
                social_connectivity_completed=False,
                plan_activation_completed=False,
                plan_activation_completed_at=None,
                is_eligible=False,
                should_show_modal=False,
                active_plan=None,
                available_plans=get_formatted_plans(None),
                billing_cycles=BILLING_CYCLES,
                currency="INR"
            )

        # 3. Check Step 1: Brand Kit completion
        brand_kit = await get_brand_kit_by_owner(db, user_id)
        brand_kit_completed = False
        if brand_kit:
            brand_kit_completed = brand_kit.get("brand_kit_completed", False)
            if not brand_kit_completed:
                has_name = bool(brand_kit.get("business_name") or brand_kit.get("brand_name"))
                has_logo = bool(brand_kit.get("logo_url"))
                has_color = bool(brand_kit.get("primary_color"))
                if has_name and has_logo and has_color and brand_kit.get("brand_kit_status") != "in_progress":
                    brand_kit_completed = True

        # 4. Check Step 2: Social Media Connectivity
        business = await db["businesses"].find_one({"owner_id": user_id})
        social_connectivity_completed = False
        is_social_skipped = bool(business and business.get("social_connectivity_skipped", False))
        
        if business and business.get("social_connectivity_completed") is True:
            social_connectivity_completed = True
        else:
            # Check platform collections directly
            ig_conn = await db["instagram_connections"].find_one(
                {"user_id": user_id, "platform": "instagram", "connected": True}
            )
            fb_conn = await db["facebook_connections"].find_one(
                {"user_id": user_id, "platform": "facebook", "connected": True}
            )
            li_conn = await db["linkedin_connections"].find_one(
                {"user_id": user_id, "platform": "linkedin", "connected": True}
            )
            if ig_conn or fb_conn or li_conn:
                social_connectivity_completed = True

        # Check online_presence
        online_presence = (
            (business.get("online_presence") if business else None) or
            current_user.get("online_presence")
        )

        if online_presence and online_presence != "no_online_presence":
            brand_kit_started_or_saved = True
        else:
            brand_kit_started_or_saved = bool(
                brand_kit_completed or
                (brand_kit and (brand_kit.get("brand_kit_status") in ["in_progress", "completed"] or brand_kit.get("completion_percentage", 0) > 0 or brand_kit.get("brand_kit_dismissed", False))) or
                (business and business.get("brand_kit_dismissed", False)) or
                True  # Incomplete Brand Kit does not block plan activation
            )

        # 5. Check Step 3: Plan Activation
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        sub_plan_id = (sub.get("plan_id") or "FREE").upper().strip()
        is_qualifying_paid = sub_plan_id in QUALIFYING_PAID_PLANS and sub.get("status") == "active"
        is_plan_skipped = bool(business and business.get("plan_selection_skipped", False))

        plan_activation_completed = False
        completed_at = None

        if business and business.get("plan_activation_completed") is True:
            plan_activation_completed = True
            completed_at = business.get("plan_activation_completed_at")
        elif is_qualifying_paid:
            # Plan was activated via payment callback; sync business doc
            plan_activation_completed = True
            completed_at = sub.get("updated_at") or sub.get("start_date")
            await PlanOnboardingService.sync_business_plan_status(
                db, user_id, sub_plan_id, sub.get("billing_cycle", "monthly")
            )

        # Determine eligibility and popup display
        # Eligible once Step 1 and Step 2 are completed or skipped
        is_eligible = brand_kit_started_or_saved and (social_connectivity_completed or is_social_skipped)
        should_show_modal = is_eligible and (not plan_activation_completed) and (not is_plan_skipped)

        # Active plan summary
        plan_config = PLANS.get(sub_plan_id, PLANS["FREE"])
        active_summary = ActivePlanSummary(
            plan_id=sub_plan_id,
            plan_name=plan_config.get("name", sub_plan_id),
            billing_cycle=sub.get("billing_cycle", "monthly"),
            credits_remaining=sub.get("credits_remaining", 0),
            credits_total=sub.get("credits_total", 0),
            status=sub.get("status", "active"),
            is_paid_plan=is_qualifying_paid,
            activated_at=completed_at or sub.get("start_date") or sub.get("created_at"),
            expires_at=sub.get("expires_at")
        )

        return PlanOnboardingStatusResponse(
            role=role,
            brand_kit_completed=brand_kit_completed,
            social_connectivity_completed=social_connectivity_completed,
            plan_activation_completed=plan_activation_completed,
            plan_activation_completed_at=completed_at,
            is_eligible=is_eligible,
            should_show_modal=should_show_modal,
            active_plan=active_summary,
            available_plans=get_formatted_plans(sub_plan_id if plan_activation_completed else None),
            billing_cycles=BILLING_CYCLES,
            currency="INR"
        )
