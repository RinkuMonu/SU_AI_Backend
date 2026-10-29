import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException, status

from app.schemas.onboarding import (
    VALID_ONLINE_PRESENCE_OPTIONS,
    BusinessOnlinePresenceType,
    PRESENCE_CANONICAL_MAP,
    CANONICAL_TO_FRONTEND_MAP,
    SUPPORTED_BUSINESS_SERVICES,
    VALID_BUSINESS_SERVICE_IDS,
    BUSINESS_SERVICE_MAP,
    BusinessServiceItem,
)

logger = logging.getLogger(__name__)

class OnboardingService:
    @staticmethod
    def normalize_online_presence(presence: Optional[str]) -> str:
        """
        Validate and normalize business online presence selection.
        Allowed values include: website, google_maps, marketplace_seller, no_online_presence, wholesale_b2b, other, something_else,
        as well as frontend source IDs: marketplace, b2b, none, social_media, directories, wholesale, etc.
        """
        if not presence or not isinstance(presence, str) or not presence.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Online presence option is required. Please choose a valid option."
            )
        clean = presence.strip().lower()
        if clean not in VALID_ONLINE_PRESENCE_OPTIONS:
            alt = clean.replace("-", "_").replace(" ", "_")
            if alt in VALID_ONLINE_PRESENCE_OPTIONS:
                clean = alt
            else:
                allowed_list = ", ".join(sorted(list(VALID_ONLINE_PRESENCE_OPTIONS)))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid online_presence selection '{presence}'. Must be one of: {allowed_list}."
                )
        return clean

    @staticmethod
    def determine_state(user_doc: Dict[str, Any], business_doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluates the user's role and database records to compute a deterministic onboarding state.
        States:
          - 'not_started': New user or role selected without online-presence or onboarding progress.
          - 'in_progress': User has chosen an online-presence or has begun onboarding steps, but not completed.
          - 'completed': Onboarding is explicitly finalized or all prerequisite steps are satisfied.
        """
        selected_services = (
            (business_doc.get("selected_services") if business_doc else None) or
            (business_doc.get("selectedServices") if business_doc else None) or
            (user_doc.get("selected_services") if user_doc else None) or
            (user_doc.get("selectedServices") if user_doc else None) or
            []
        )

        if not user_doc:
            return {
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "canonical_presence": None,
                "business_source": None,
                "presence": None,
                "selling_model": None,
                "selected_platforms": [],
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
                "canonical_presence": None,
                "business_source": None,
                "presence": None,
                "selling_model": None,
                "selected_platforms": [],
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
                "canonical_presence": None,
                "business_source": None,
                "presence": None,
                "selling_model": None,
                "selected_platforms": [],
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
                "canonical_presence": None,
                "business_source": None,
                "presence": None,
                "selling_model": None,
                "selected_platforms": [],
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
        selling_model = (
            user_doc.get("selling_model") or
            (business_doc.get("selling_model") if business_doc else None)
        )
        business_source = (
            user_doc.get("business_source") or
            (business_doc.get("business_source") if business_doc else None) or
            online_presence
        )
        canonical_presence = (
            user_doc.get("canonical_presence") or
            (business_doc.get("canonical_presence") if business_doc else None) or
            (PRESENCE_CANONICAL_MAP.get(online_presence) if online_presence else None)
        )
        selected_platforms = (
            user_doc.get("selected_platforms") or
            (business_doc.get("selected_platforms") if business_doc else None) or
            []
        )

        # Fallback: if online_presence is not set but business_type matches valid options
        if not online_presence and business_type and business_type.lower() in VALID_ONLINE_PRESENCE_OPTIONS:
            online_presence = business_type.lower()
            canonical_presence = PRESENCE_CANONICAL_MAP.get(online_presence, online_presence)

        onboarding_step = user_doc.get("onboarding_step", 1) or 1

        if is_completed:
            return {
                "role": "businessman",
                "onboarding_status": "completed",
                "onboarding_step": max(onboarding_step, 2),
                "online_presence": online_presence,
                "canonical_presence": canonical_presence,
                "business_source": business_source,
                "presence": online_presence,
                "business_type": business_type or online_presence,
                "selling_model": selling_model,
                "selected_platforms": selected_platforms,
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
                "canonical_presence": None,
                "business_source": None,
                "presence": None,
                "business_type": business_type,
                "selling_model": selling_model,
                "selected_platforms": [],
                "selected_services": selected_services,
                "selectedServices": selected_services,
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
            "canonical_presence": canonical_presence,
            "business_source": business_source,
            "presence": online_presence,
            "business_type": business_type or online_presence,
            "selling_model": selling_model,
            "selected_platforms": selected_platforms,
            "selected_services": selected_services,
            "selectedServices": selected_services,
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
        raw_presence = (
            payload_dict.get("online_presence") or
            payload_dict.get("presence") or
            payload_dict.get("source") or
            payload_dict.get("business_source") or
            payload_dict.get("onlinePresence")
        )
        presence = OnboardingService.normalize_online_presence(raw_presence)
        canonical_presence = PRESENCE_CANONICAL_MAP.get(presence, presence)
        now = datetime.now(timezone.utc)

        # Build update document
        user_updates: Dict[str, Any] = {
            "online_presence": presence,
            "canonical_presence": canonical_presence,
            "business_source": presence,
            "presence": presence,
            "business_type": payload_dict.get("business_type") or presence,
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        if payload_dict.get("selling_model"):
            user_updates["selling_model"] = str(payload_dict["selling_model"]).strip()
        if payload_dict.get("google_maps_url"):
            user_updates["google_maps_url"] = str(payload_dict["google_maps_url"]).strip()
        if payload_dict.get("website_url") or payload_dict.get("website"):
            user_updates["website"] = str(payload_dict.get("website_url") or payload_dict.get("website")).strip()

        # Optional selected_services in online_presence payload
        srv_input = payload_dict.get("selected_services") or payload_dict.get("selectedServices")
        norm_srv_ids = None
        service_items = None
        if srv_input is not None:
            norm_srv_ids, service_items = OnboardingService.validate_and_normalize_services(srv_input)
            user_updates["selected_services"] = norm_srv_ids
            user_updates["selectedServices"] = norm_srv_ids

        # Support selected platforms for marketplace_seller and wholesale_b2b
        norm_platforms = None
        platform_items = None
        clean_custom = None
        is_none = False
        if payload_dict.get("selected_platforms") is not None:
            from app.services.platform_onboarding_service import PlatformOnboardingService
            custom_name = payload_dict.get("custom_platform_name") or payload_dict.get("other_platform_name") or payload_dict.get("custom_listing_name")
            norm_ids, platform_items, clean_custom, is_none = PlatformOnboardingService.validate_and_normalize_platforms(
                source=canonical_presence,
                selected_platforms=payload_dict["selected_platforms"],
                custom_platform_name=custom_name
            )
            norm_platforms = norm_ids
            user_updates["selected_platforms"] = norm_ids

        if payload_dict.get("directory_listings") is not None:
            user_updates["directory_listings"] = payload_dict["directory_listings"]
        if payload_dict.get("additional_listings") is not None:
            user_updates["additional_listings"] = payload_dict["additional_listings"]
        if payload_dict.get("custom_listing_name"):
            user_updates["custom_listing_name"] = str(payload_dict["custom_listing_name"]).strip()
        if payload_dict.get("skip_website") is not None or payload_dict.get("website_skipped") is not None:
            user_updates["skip_website"] = bool(payload_dict.get("skip_website") if payload_dict.get("skip_website") is not None else payload_dict.get("website_skipped"))

        # Check existing step; advance to 2 if currently <= 1
        u_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        is_pending = False
        if not u_doc:
            u_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
            is_pending = True

        current_step = u_doc.get("onboarding_step", 1) if u_doc else 1
        new_step = max(current_step, 2)
        user_updates["onboarding_step"] = new_step

        # Always persist user updates to canonical users collection
        if ObjectId.is_valid(user_id):
            await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_updates}
            )
            if is_pending or await db["pending_users"].find_one({"_id": ObjectId(user_id)}):
                await db["pending_users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": user_updates}
                )

        # Update or create business document
        business_updates: Dict[str, Any] = {
            "owner_id": str(user_id),
            "ownerId": str(user_id),
            "user_id": str(user_id),
            "online_presence": presence,
            "canonical_presence": canonical_presence,
            "business_source": presence,
            "presence": presence,
            "business_type": user_updates["business_type"],
            "updated_at": now
        }
        if "selling_model" in user_updates:
            business_updates["selling_model"] = user_updates["selling_model"]
        if norm_srv_ids is not None:
            business_updates["selected_services"] = norm_srv_ids
            business_updates["selectedServices"] = norm_srv_ids
            if service_items:
                business_updates["service_details"] = [item.model_dump() for item in service_items]

        if "google_maps_url" in user_updates:
            business_updates["google_maps_url"] = user_updates["google_maps_url"]
        if "website" in user_updates:
            business_updates["website"] = user_updates["website"]
        if payload_dict.get("business_name"):
            business_updates["business_name"] = str(payload_dict["business_name"]).strip()
            business_updates["name"] = str(payload_dict["business_name"]).strip()
        if payload_dict.get("category"):
            business_updates["category"] = str(payload_dict["category"]).strip()
        if payload_dict.get("description"):
            business_updates["description"] = str(payload_dict["description"]).strip()

        if norm_platforms is not None:
            business_updates["selected_platforms"] = norm_platforms
            business_updates["platform_details"] = [p.model_dump() for p in platform_items]
            business_updates["none_of_these_selected"] = is_none
            if clean_custom:
                business_updates["custom_platform_name"] = clean_custom
                business_updates["other_platform_name"] = clean_custom

        if "directory_listings" in user_updates:
            business_updates["directory_listings"] = user_updates["directory_listings"]
        if "additional_listings" in user_updates:
            business_updates["additional_listings"] = user_updates["additional_listings"]
        if "custom_listing_name" in user_updates:
            business_updates["custom_listing_name"] = user_updates["custom_listing_name"]
        if "skip_website" in user_updates:
            business_updates["skip_website"] = user_updates["skip_website"]
            business_updates["website_skipped"] = user_updates["skip_website"]

        if payload_dict.get("marketplace_url"):
            business_updates["marketplace_url"] = str(payload_dict["marketplace_url"]).strip()

        if payload_dict.get("platform_urls"):
            business_updates["platform_urls"] = payload_dict["platform_urls"]

        if payload_dict.get("has_storefront") is not None:
            business_updates["has_storefront"] = bool(payload_dict["has_storefront"])

        bus_defaults = {
            "name": business_updates.get("business_name") or "My Business",
            "business_name": business_updates.get("business_name") or "My Business",
            "category": "General",
            "location": "India",
            "created_at": now
        }
        only_bus_insert = {k: v for k, v in bus_defaults.items() if k not in business_updates}
        bus_op = {"$set": business_updates}
        if only_bus_insert:
            bus_op["$setOnInsert"] = only_bus_insert

        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            bus_op,
            upsert=True
        )

        # Sync to brand kit if exists (do not upsert a ghost brand kit)
        try:
            await db["brand_kits"].update_one(
                {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
                {
                    "$set": {
                        "business_type": user_updates["business_type"],
                        "online_presence": presence,
                        "canonical_presence": canonical_presence,
                        "updated_at": now
                    }
                }
            )
        except Exception as e:
            logger.debug(f"Could not sync brand_kit online_presence: {e}")

        # Also sync to platform_onboarding_jobs if source is marketplace or b2b
        if canonical_presence in ("marketplace_seller", "wholesale_b2b"):
            try:
                job_set = {
                    "onboarding_source": canonical_presence,
                    "raw_source": presence,
                    "updated_at": now
                }
                if norm_platforms is not None:
                    job_set["selected_platforms"] = norm_platforms
                if clean_custom:
                    job_set["custom_platform_name"] = clean_custom
                if "directory_listings" in user_updates:
                    job_set["directory_listings"] = user_updates["directory_listings"]
                if "additional_listings" in user_updates:
                    job_set["additional_listings"] = user_updates["additional_listings"]
                if "custom_listing_name" in user_updates:
                    job_set["custom_listing_name"] = user_updates["custom_listing_name"]
                if "skip_website" in user_updates:
                    job_set["skip_website"] = user_updates["skip_website"]

                await db["platform_onboarding_jobs"].update_one(
                    {"user_id": str(user_id)},
                    {
                        "$set": job_set,
                        "$setOnInsert": {
                            "job_id": f"pl_{user_id}",
                            "status": "pending",
                            "created_at": now
                        }
                    },
                    upsert=True
                )
            except Exception as e:
                logger.debug(f"Could not sync platform_onboarding_job: {e}")

        # Fetch refreshed docs to calculate state
        refreshed_user = await db["users"].find_one({"_id": ObjectId(user_id)}) or await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        refreshed_bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]})

        state = OnboardingService.determine_state(refreshed_user or user_updates, refreshed_bus)
        return {
            "success": True,
            "message": "Business online presence saved successfully.",
            "online_presence": presence,
            "canonical_presence": canonical_presence,
            "business_source": presence,
            "presence": presence,
            "business_type": user_updates["business_type"],
            "selling_model": user_updates.get("selling_model"),
            "selected_platforms": user_updates.get("selected_platforms"),
            "directory_listings": user_updates.get("directory_listings"),
            "additional_listings": user_updates.get("additional_listings"),
            "onboarding_step": new_step,
            "onboarding_status": "in_progress",
            "next_step": state["next_step"],
            "can_access_dashboard": state["can_access_dashboard"],
            "data": state
        }

    @staticmethod
    def validate_and_normalize_services(selected_services: Any) -> Tuple[List[str], List[BusinessServiceItem]]:
        """
        Validates an array of selected business service IDs against the supported service catalog.
        - Enforces that input is a list/array.
        - Rejects any unknown or invalid service IDs with a clear 400 validation error.
        - Deduplicates IDs safely while preserving order.
        - Returns a tuple of (normalized_ids, service_items).
        """
        if selected_services is None:
            return [], []
        if not isinstance(selected_services, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="selectedServices must be an array of service identifiers."
            )

        seen = set()
        deduped: List[str] = []
        for raw_id in selected_services:
            if not isinstance(raw_id, str):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Service ID must be a string, got {type(raw_id).__name__}."
                )
            clean_id = raw_id.strip()
            if not clean_id:
                continue
            if clean_id not in VALID_BUSINESS_SERVICE_IDS:
                allowed_ids = ", ".join(sorted(list(VALID_BUSINESS_SERVICE_IDS)))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid business service '{raw_id}'. Allowed services are: {allowed_ids}."
                )
            if clean_id not in seen:
                seen.add(clean_id)
                deduped.append(clean_id)

        items = [BusinessServiceItem(**BUSINESS_SERVICE_MAP[s_id]) for s_id in deduped]
        return deduped, items

    @staticmethod
    async def save_selected_services(db, user_id: str, selected_services: Any) -> Dict[str, Any]:
        """
        Validates, deduplicates, and saves the business service selections for the authenticated user and their business.
        Updates choices persistently in both users (or pending_users) and businesses collections.
        """
        norm_ids, service_items = OnboardingService.validate_and_normalize_services(selected_services)
        now = datetime.now(timezone.utc)

        # Check if user is in users or pending_users
        is_pending = False
        u_doc = None
        try:
            u_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        except Exception:
            pass
        if not u_doc:
            try:
                u_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
                is_pending = True
            except Exception:
                pass

        # Always persist user updates to canonical users collection
        if ObjectId.is_valid(user_id):
            await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    "selected_services": norm_ids,
                    "selectedServices": norm_ids,
                    "updated_at": now
                }}
            )
            if is_pending or await db["pending_users"].find_one({"_id": ObjectId(user_id)}):
                await db["pending_users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {
                        "selected_services": norm_ids,
                        "selectedServices": norm_ids,
                        "updated_at": now
                    }}
                )

        # Update or upsert business document
        business_updates = {
            "owner_id": str(user_id),
            "ownerId": str(user_id),
            "user_id": str(user_id),
            "selected_services": norm_ids,
            "selectedServices": norm_ids,
            "service_details": [item.model_dump() for item in service_items],
            "updated_at": now
        }
        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {
                "$set": business_updates,
                "$setOnInsert": {
                    "name": "My Business",
                    "business_name": "My Business",
                    "category": "General",
                    "location": "India",
                    "created_at": now
                }
            },
            upsert=True
        )

        return {
            "success": True,
            "message": "Business services saved successfully.",
            "selected_services": norm_ids,
            "selectedServices": norm_ids,
            "services": [item.model_dump() for item in service_items],
            "service_details": [item.model_dump() for item in service_items],
            "count": len(norm_ids)
        }

    @staticmethod
    async def get_selected_services(db, user_id: str) -> Dict[str, Any]:
        """
        Retrieves the authenticated user's saved business service selections.
        """
        bus_doc = await db["businesses"].find_one({"$or": [
            {"owner_id": str(user_id)},
            {"ownerId": str(user_id)},
            {"user_id": str(user_id)},
            {"userId": str(user_id)}
        ]}) or {}

        u_doc = None
        try:
            u_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        except Exception:
            pass
        if not u_doc:
            try:
                u_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
            except Exception:
                pass
        if not u_doc:
            u_doc = {}

        raw_services = (
            bus_doc.get("selected_services") or
            bus_doc.get("selectedServices") or
            u_doc.get("selected_services") or
            u_doc.get("selectedServices") or
            []
        )

        valid_ids = [s for s in raw_services if s in VALID_BUSINESS_SERVICE_IDS]
        seen = set()
        deduped = []
        for s in valid_ids:
            if s not in seen:
                seen.add(s)
                deduped.append(s)

        service_items = [BusinessServiceItem(**BUSINESS_SERVICE_MAP[s_id]) for s_id in deduped]

        return {
            "success": True,
            "message": "Selected business services retrieved successfully.",
            "selected_services": deduped,
            "selectedServices": deduped,
            "services": [item.model_dump() for item in service_items],
            "service_details": [item.model_dump() for item in service_items],
            "count": len(deduped)
        }

    @staticmethod
    def get_services_catalog() -> Dict[str, Any]:
        """
        Returns the catalog of all supported business services.
        """
        items = [BusinessServiceItem(**s) for s in SUPPORTED_BUSINESS_SERVICES]
        return {
            "success": True,
            "services": [item.model_dump() for item in items],
            "count": len(items)
        }
