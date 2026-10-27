import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException, status

from app.schemas.onboarding import VALID_ONLINE_PRESENCE_OPTIONS, BusinessOnlinePresenceType

logger = logging.getLogger(__name__)

class OnboardingService:
    @staticmethod
    def normalize_online_presence(presence: Optional[str]) -> str:
        """
        Validate and normalize business online presence selection.
        Allowed values: website, google_maps, marketplace_seller, no_online_presence, wholesale_b2b, other, something_else.
        """
        if not presence or not isinstance(presence, str) or not presence.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Online presence option is required. Please choose a valid option."
            )
        normalized = presence.strip().lower()
        if normalized not in VALID_ONLINE_PRESENCE_OPTIONS:
            allowed_list = ", ".join(sorted(list(VALID_ONLINE_PRESENCE_OPTIONS)))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid online_presence selection '{presence}'. Must be one of: {allowed_list}."
            )
        return normalized

    @staticmethod
    def determine_state(user_doc: Dict[str, Any], business_doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluates the user's role and database records to compute a deterministic onboarding state.
        States:
          - 'not_started': New user or role selected without online-presence or onboarding progress.
          - 'in_progress': User has chosen an online-presence or has begun onboarding steps, but not completed.
          - 'completed': Onboarding is explicitly finalized or all prerequisite steps are satisfied.
        """
        if not user_doc:
            return {
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "onboarding_completed": False,
                "onboardingCompleted": False,
                "can_access_dashboard": False,
                "requires_onboarding": True,
                "requires_role_selection": True,
                "next_step": "role_selection",
                "dashboard_route": "/select-role",
                "onboarding_route": "/select-role"
            }

        # Check role
        raw_role = user_doc.get("role")
        role = None
        if raw_role:
            r = str(raw_role).lower().strip()
            if r in ["businessman", "business", "merchant", "brand", "entrepreneur", "corporate"]:
                role = "businessman"
            elif r in ["influencer", "creator"]:
                role = "influencer"
            elif r in ["admin", "administrator", "superuser"]:
                role = "admin"
            elif r not in ["", "none", "null", "user"]:
                role = r

        # 1. No role selected yet
        if not role:
            return {
                "role": None,
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "onboarding_completed": False,
                "onboardingCompleted": False,
                "can_access_dashboard": False,
                "requires_onboarding": True,
                "requires_role_selection": True,
                "next_step": "role_selection",
                "dashboard_route": "/select-role",
                "onboarding_route": "/select-role"
            }

        # 2. Influencer or Admin roles do not require business online presence onboarding
        if role == "influencer":
            return {
                "role": "influencer",
                "onboarding_status": "completed",
                "onboarding_step": 1,
                "online_presence": None,
                "onboarding_completed": True,
                "onboardingCompleted": True,
                "can_access_dashboard": True,
                "requires_onboarding": False,
                "requires_role_selection": False,
                "next_step": "dashboard",
                "dashboard_route": "/dashboard/creator",
                "onboarding_route": "/dashboard/creator"
            }

        if role == "admin":
            return {
                "role": "admin",
                "onboarding_status": "completed",
                "onboarding_step": 1,
                "online_presence": None,
                "onboarding_completed": True,
                "onboardingCompleted": True,
                "can_access_dashboard": True,
                "requires_onboarding": False,
                "requires_role_selection": False,
                "next_step": "dashboard",
                "dashboard_route": "/admin/dashboard",
                "onboarding_route": "/admin/dashboard"
            }

        # 3. Businessman role
        is_completed = bool(
            user_doc.get("onboardingCompleted", False) or
            user_doc.get("onboarding_completed_at")
        )

        online_presence = (
            user_doc.get("online_presence") or
            (business_doc.get("online_presence") if business_doc else None)
        )
        business_type = (
            user_doc.get("business_type") or
            (business_doc.get("business_type") if business_doc else None)
        )

        # Fallback: if online_presence is not set but business_type matches valid options
        if not online_presence and business_type and business_type.lower() in VALID_ONLINE_PRESENCE_OPTIONS:
            online_presence = business_type.lower()

        onboarding_step = user_doc.get("onboarding_step", 1) or 1

        if is_completed:
            return {
                "role": "businessman",
                "onboarding_status": "completed",
                "onboarding_step": max(onboarding_step, 2),
                "online_presence": online_presence,
                "business_type": business_type or online_presence,
                "onboarding_completed": True,
                "onboardingCompleted": True,
                "can_access_dashboard": True,
                "requires_onboarding": False,
                "requires_role_selection": False,
                "next_step": "dashboard",
                "dashboard_route": "/dashboard/business",
                "onboarding_route": "/dashboard/business"
            }

        # User is incomplete
        if not online_presence:
            return {
                "role": "businessman",
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "business_type": business_type,
                "onboarding_completed": False,
                "onboardingCompleted": False,
                "can_access_dashboard": False,
                "requires_onboarding": True,
                "requires_role_selection": False,
                "next_step": "online_presence",
                "dashboard_route": "/dashboard/business",
                "onboarding_route": "/onboarding?step=online_presence"
            }

        # User has selected online_presence, next steps pending
        effective_step = max(onboarding_step, 2)
        next_step_name = "brand_kit" if effective_step == 2 else ("social_connectivity" if effective_step == 3 else "subscription_plan")

        return {
            "role": "businessman",
            "onboarding_status": "in_progress",
            "onboarding_step": effective_step,
            "online_presence": online_presence,
            "business_type": business_type or online_presence,
            "onboarding_completed": False,
            "onboardingCompleted": False,
            "can_access_dashboard": False,
            "requires_onboarding": True,
            "requires_role_selection": False,
            "next_step": next_step_name,
            "dashboard_route": "/dashboard/business",
            "onboarding_route": f"/onboarding?step={next_step_name}"
        }

    @staticmethod
    async def save_online_presence(db, user_id: str, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates, canonicalizes, and persists the business online presence for a user and business document.
        Advances onboarding_step to at least 2 and marks onboarding_status as 'in_progress'.
        """
        raw_presence = payload_dict.get("online_presence")
        presence = OnboardingService.normalize_online_presence(raw_presence)
        now = datetime.now(timezone.utc)

        # Build update document
        user_updates: Dict[str, Any] = {
            "online_presence": presence,
            "business_type": payload_dict.get("business_type") or presence,
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        if payload_dict.get("google_maps_url"):
            user_updates["google_maps_url"] = str(payload_dict["google_maps_url"]).strip()
        if payload_dict.get("website_url") or payload_dict.get("website"):
            user_updates["website"] = str(payload_dict.get("website_url") or payload_dict.get("website")).strip()

        # Check existing step; advance to 2 if currently <= 1
        u_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        is_pending = False
        if not u_doc:
            u_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
            is_pending = True

        current_step = u_doc.get("onboarding_step", 1) if u_doc else 1
        new_step = max(current_step, 2)
        user_updates["onboarding_step"] = new_step

        target_coll = db["pending_users"] if is_pending else db["users"]
        await target_coll.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": user_updates}
        )

        # Update or create business document
        business_updates: Dict[str, Any] = {
            "owner_id": str(user_id),
            "ownerId": str(user_id),
            "online_presence": presence,
            "business_type": user_updates["business_type"],
            "updated_at": now
        }
        if "google_maps_url" in user_updates:
            business_updates["google_maps_url"] = user_updates["google_maps_url"]
        if "website" in user_updates:
            business_updates["website"] = user_updates["website"]
        if payload_dict.get("business_name"):
            business_updates["business_name"] = str(payload_dict["business_name"]).strip()
        if payload_dict.get("category"):
            business_updates["category"] = str(payload_dict["category"]).strip()
        if payload_dict.get("description"):
            business_updates["description"] = str(payload_dict["description"]).strip()

        # Support selected platforms for marketplace_seller and wholesale_b2b
        if payload_dict.get("selected_platforms"):
            from app.services.platform_onboarding_service import PlatformOnboardingService
            custom_name = payload_dict.get("custom_platform_name") or payload_dict.get("other_platform_name")
            norm_ids, platform_items, clean_custom, is_none = PlatformOnboardingService.validate_and_normalize_platforms(
                source=presence,
                selected_platforms=payload_dict["selected_platforms"],
                custom_platform_name=custom_name
            )
            user_updates["selected_platforms"] = norm_ids
            business_updates["selected_platforms"] = norm_ids
            business_updates["platform_details"] = [p.model_dump() for p in platform_items]
            business_updates["none_of_these_selected"] = is_none
            if clean_custom:
                business_updates["custom_platform_name"] = clean_custom
                business_updates["other_platform_name"] = clean_custom

        if payload_dict.get("marketplace_url"):
            business_updates["marketplace_url"] = str(payload_dict["marketplace_url"]).strip()

        if payload_dict.get("platform_urls"):
            business_updates["platform_urls"] = payload_dict["platform_urls"]

        if payload_dict.get("website_skipped") is not None:
            business_updates["website_skipped"] = bool(payload_dict["website_skipped"])
        if payload_dict.get("has_storefront") is not None:
            business_updates["has_storefront"] = bool(payload_dict["has_storefront"])

        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {"$set": business_updates},
            upsert=True
        )

        # Sync to brand kit if exists
        try:
            await db["brand_kits"].update_one(
                {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
                {"$set": {"business_type": user_updates["business_type"], "online_presence": presence, "updated_at": now}}
            )
        except Exception as e:
            logger.debug(f"Could not sync brand_kit online_presence: {e}")

        # Fetch refreshed docs to calculate state
        refreshed_user = await db["users"].find_one({"_id": ObjectId(user_id)}) or await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        refreshed_bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]})

        state = OnboardingService.determine_state(refreshed_user or user_updates, refreshed_bus)
        return {
            "success": True,
            "message": "Business online presence saved successfully.",
            "online_presence": presence,
            "business_type": user_updates["business_type"],
            "onboarding_step": new_step,
            "onboarding_status": "in_progress",
            "next_step": state["next_step"],
            "can_access_dashboard": state["can_access_dashboard"],
            "data": state
        }
