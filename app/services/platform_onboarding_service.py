import asyncio
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from fastapi import HTTPException, status

from app.schemas.platform_onboarding import (
    B2B_NAME_MAP,
    MARKETPLACE_NAME_MAP,
    SUPPORTED_B2B_PLATFORMS,
    SUPPORTED_MARKETPLACE_PLATFORMS,
    PlatformCatalogItem,
    PlatformCatalogResponse,
    PlatformItem,
    PlatformOnboardingState,
    PlatformUrlAnalysisResponse,
    PlatformWebsiteSubmissionResponse,
    SavePlatformsRequest,
)
from app.schemas.website_analysis import WebsiteAnalysisCreateRequest
from app.services.onboarding_service import OnboardingService
from app.services.website_analysis_service import WebsiteAnalysisService
from app.utils.url_validator import normalize_website_url, validate_url_safety

logger = logging.getLogger(__name__)

SUPPORTED_ONBOARDING_SOURCES = {
    "marketplace",
    "marketplace_seller",
    "b2b",
    "wholesale",
    "wholesale_b2b",
    "directories",
    "website",
    "google_maps",
    "no_online_presence",
    "none",
    "social_media",
    "other",
    "something_else"
}


class PlatformOnboardingService:
    """
    Dedicated service managing Marketplace Seller and Wholesale/B2B onboarding workflows:
    - Platform selection validation (multiple selections, mutual exclusion for 'None of these', custom 'Other')
    - Canonical multi-collection persistence (businesses, users, platform_onboarding_jobs)
    - Safe partial update preservation
    - Seamless reuse of WebsiteAnalysisService for optional storefront URLs without overwriting presence
    - Manual entry / skip workflow
    - Full state restoration on refresh or re-login
    """

    @classmethod
    def canonical_source(cls, source: Optional[str]) -> str:
        """Normalizes any valid onboarding source or alias into canonical form."""
        if not source:
            return "marketplace_seller"
        clean = source.strip().lower()
        if clean in ("wholesale_b2b", "b2b", "wholesale", "directories"):
            return "wholesale_b2b"
        elif clean in ("marketplace_seller", "marketplace"):
            return "marketplace_seller"
        elif clean in ("no_online_presence", "none"):
            return "no_online_presence"
        return clean

    @staticmethod
    def normalize_platform_id(raw_id: str) -> str:
        """Normalizes a platform string into a canonical ID."""
        if not raw_id:
            return ""
        clean = raw_id.strip().lower()

        # Common alias mappings
        aliases = {
            "none": "none_of_these",
            "none of these": "none_of_these",
            "none of the above": "none_of_these",
            "none-of-these": "none_of_these",
            "swiggy instamart": "instamart",
            "swiggy": "instamart",
            "tata 1mg": "tata_1mg",
            "1mg": "tata_1mg",
            "indiamart": "indiamart",
            "india mart": "indiamart",
            "trade india": "tradeindia",
            "just dial": "justdial",
            "exporters india": "exportersindia",
            "power 2 sme": "power2sme",
            "amazon business": "amazon_business",
            "other": "other"
        }
        if clean in aliases:
            return aliases[clean]

        # General normalization: replace punctuation and spaces with underscores
        normalized = re.sub(r"[\s\-\.]+", "_", clean)
        normalized = re.sub(r"[^a-z0-9_]", "", normalized)
        return normalized.strip("_")

    @classmethod
    def get_catalog(cls, onboarding_source: Optional[str] = None) -> PlatformCatalogResponse:
        """Returns standard catalogue options for the given onboarding source."""
        canonical_source = cls.canonical_source(onboarding_source)
        if canonical_source == "wholesale_b2b":
            items = [PlatformCatalogItem(**p) for p in SUPPORTED_B2B_PLATFORMS]
        else:
            canonical_source = "marketplace_seller"
            items = [PlatformCatalogItem(**p) for p in SUPPORTED_MARKETPLACE_PLATFORMS]

        return PlatformCatalogResponse(
            success=True,
            onboarding_source=canonical_source,
            platforms=items
        )

    @classmethod
    def validate_and_normalize_platforms(
        cls,
        source: str,
        selected_platforms: List[str],
        custom_platform_name: Optional[str] = None
    ) -> Tuple[List[str], List[PlatformItem], Optional[str], bool]:
        """
        Validates platform selections according to business rules:
        1. Enforces non-empty selections.
        2. Deduplicates platform IDs while preserving user ordering.
        3. Enforces mutual exclusivity for 'None of these' in B2B/directory flows.
        4. Enforces required custom platform name (min 2 chars) when 'Other' is selected.
        5. Formats structured PlatformItem representations.
        """
        norm_source = cls.canonical_source(source)

        # 1. Normalize and deduplicate
        seen = set()
        normalized_ids: List[str] = []
        for raw in (selected_platforms or []):
            nid = cls.normalize_platform_id(raw)
            if nid and nid not in seen:
                seen.add(nid)
                normalized_ids.append(nid)

        if not normalized_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one valid platform must be selected."
            )

        # 2. Check mutual exclusivity for 'none_of_these'
        is_none_selected = "none_of_these" in normalized_ids
        if is_none_selected and len(normalized_ids) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="When 'None of these' is selected, you cannot select specific platforms."
            )

        # 3. Check custom name for 'other'
        cleaned_custom_name = None
        has_other = "other" in normalized_ids
        if has_other:
            clean_name = (custom_platform_name or "").strip()
            if len(clean_name) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please provide a valid custom platform name (at least 2 characters) when 'Other' is selected."
                )
            cleaned_custom_name = clean_name

        # 4. Build structured PlatformItem list
        category = "directory" if norm_source == "wholesale_b2b" else "marketplace"
        name_map = B2B_NAME_MAP if norm_source == "wholesale_b2b" else MARKETPLACE_NAME_MAP

        platform_items: List[PlatformItem] = []
        for pid in normalized_ids:
            if pid == "other" and cleaned_custom_name:
                p_name = cleaned_custom_name
                is_custom = True
            elif pid in name_map:
                p_name = name_map[pid]
                is_custom = False
            else:
                p_name = pid.replace("_", " ").title()
                is_custom = True

            platform_items.append(
                PlatformItem(
                    id=pid,
                    name=p_name,
                    category=category,
                    is_custom=is_custom
                )
            )

        return normalized_ids, platform_items, cleaned_custom_name, is_none_selected

    @classmethod
    async def save_platform_selections(
        cls,
        db,
        user_id: str,
        payload: SavePlatformsRequest
    ) -> PlatformOnboardingState:
        """
        Validates, canonicalizes, and persists platform selections across businesses,
        users, and platform_onboarding_jobs collections.
        Preserves previously saved values when partial updates are submitted.
        """
        now = datetime.now(timezone.utc)
        uid = str(user_id)

        # 1. Determine onboarding source
        raw_source = payload.onboarding_source
        existing_job = await db["platform_onboarding_jobs"].find_one({"user_id": uid}) or {}
        existing_bus = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]}) or {}
        u_doc = await db["users"].find_one({"_id": ObjectId(uid)}) or await db["pending_users"].find_one({"_id": ObjectId(uid)}) or {}

        if not raw_source:
            raw_source = existing_job.get("onboarding_source") or existing_bus.get("online_presence") or u_doc.get("online_presence") or "marketplace_seller"
        source = cls.canonical_source(raw_source)

        custom_name = payload.custom_platform_name or payload.other_platform_name

        # 1b. Fallback to existing selected platforms if omitted in partial update
        raw_platforms = payload.selected_platforms
        if raw_platforms is None or len(raw_platforms) == 0:
            existing_platforms = (
                existing_job.get("selected_platforms") or
                existing_bus.get("selected_platforms") or
                u_doc.get("selected_platforms") or
                []
            )
            if existing_platforms:
                raw_platforms = existing_platforms
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="At least one valid platform must be selected."
                )

        # 2. Validate and normalize platforms
        norm_ids, platform_items, clean_custom, is_none = cls.validate_and_normalize_platforms(
            source=source,
            selected_platforms=raw_platforms,
            custom_platform_name=custom_name
        )

        # 2b. Normalize directory / additional listings
        directory_listings: List[str] = []
        if payload.directory_listings:
            seen_dl = set()
            for raw_dl in payload.directory_listings:
                nid = cls.normalize_platform_id(raw_dl)
                if nid and nid not in seen_dl:
                    seen_dl.add(nid)
                    directory_listings.append(nid)
        elif "directory_listings" in existing_bus or "directory_listings" in existing_job:
            directory_listings = existing_bus.get("directory_listings") or existing_job.get("directory_listings") or []

        additional_listings: List[str] = []
        if payload.additional_listings:
            seen_al = set()
            for raw_al in payload.additional_listings:
                nid = cls.normalize_platform_id(raw_al)
                if nid and nid not in seen_al:
                    seen_al.add(nid)
                    additional_listings.append(nid)
        elif "additional_listings" in existing_bus or "additional_listings" in existing_job:
            additional_listings = existing_bus.get("additional_listings") or existing_job.get("additional_listings") or []

        clean_listing_name = (payload.custom_listing_name or "").strip() or None
        if not clean_listing_name:
            clean_listing_name = existing_bus.get("custom_listing_name") or existing_job.get("custom_listing_name")

        # 3. Handle optional website URL
        norm_url = None
        skipped_website = bool(payload.skip_website)
        if payload.website_url and not skipped_website:
            try:
                norm_url = normalize_website_url(payload.website_url)
                is_safe, err_msg = validate_url_safety(norm_url, allow_private_for_tests=True)
                if not is_safe:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=err_msg or "Invalid website URL."
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid website URL: {str(e)}"
                )

        # 3b. Handle multi-platform URLs (Marketplace Seller & Wholesale/B2B)
        # Load existing platform URLs and statuses to guarantee partial updates and retries never wipe successful results
        platform_urls: Dict[str, str] = dict(existing_job.get("platform_urls") or existing_bus.get("platform_urls") or {})
        platform_analysis_status: Dict[str, str] = dict(existing_job.get("platform_analysis_status") or existing_bus.get("platform_analysis_status") or {})
        platform_analysis_errors: Dict[str, str] = dict(existing_job.get("platform_analysis_errors") or {})
        platform_analysis_jobs: Dict[str, str] = dict(existing_job.get("platform_analysis_jobs") or {})

        # Ingest incoming platform URLs
        incoming_urls: Dict[str, str] = {}
        if payload.platform_urls and isinstance(payload.platform_urls, dict):
            for raw_k, raw_v in payload.platform_urls.items():
                if raw_v and str(raw_v).strip():
                    norm_k = cls.normalize_platform_id(raw_k)
                    incoming_urls[norm_k] = str(raw_v).strip()

        if payload.urls and isinstance(payload.urls, list):
            for entry in payload.urls:
                if isinstance(entry, dict):
                    p_id = entry.get("platform") or entry.get("id") or entry.get("platform_id")
                    p_url = entry.get("url") or entry.get("website_url")
                    if p_id and p_url and str(p_url).strip():
                        norm_k = cls.normalize_platform_id(p_id)
                        incoming_urls[norm_k] = str(p_url).strip()

        # Validate and process each incoming platform URL with SSRF protection
        for p_id, raw_p_url in incoming_urls.items():
            try:
                norm_p_url = normalize_website_url(raw_p_url)
                is_safe, err_msg = validate_url_safety(norm_p_url, allow_private_for_tests=False)
                if not is_safe:
                    platform_analysis_status[p_id] = "failed"
                    platform_analysis_errors[p_id] = err_msg or "URL blocked by security safety policy."
                    platform_urls[p_id] = norm_p_url
                    continue

                # Safe URL
                platform_urls[p_id] = norm_p_url
                platform_analysis_errors.pop(p_id, None)

                # Launch or reuse website analysis job for this platform URL
                try:
                    w_job = await WebsiteAnalysisService.create_analysis_job(
                        db=db,
                        user_id=uid,
                        payload=WebsiteAnalysisCreateRequest(
                            url=norm_p_url,
                            onboarding_type=source
                        ),
                        allow_private_for_tests=True
                    )
                    platform_analysis_status[p_id] = "pending"
                    platform_analysis_jobs[p_id] = w_job.job_id
                except Exception as ex:
                    logger.warning(f"Error launching analysis for platform {p_id} ({norm_p_url}): {ex}")
                    platform_analysis_status[p_id] = "failed"
                    platform_analysis_errors[p_id] = str(ex)
            except Exception as e:
                logger.warning(f"Invalid URL for platform {p_id}: {e}")
                platform_analysis_status[p_id] = "failed"
                platform_analysis_errors[p_id] = str(e)
                platform_urls[p_id] = raw_p_url

        # Update platform_items with URL and status metadata
        for item in platform_items:
            item.url = platform_urls.get(item.id)
            item.analysis_status = platform_analysis_status.get(item.id)
            item.error = platform_analysis_errors.get(item.id)

        # 4. Update businesses collection (with owner_id on upsert)
        bus_update: Dict[str, Any] = {
            "owner_id": uid,
            "ownerId": uid,
            "online_presence": source,
            "business_type": source,
            "selected_platforms": norm_ids,
            "directory_listings": directory_listings,
            "additional_listings": additional_listings,
            "platform_details": [p.model_dump() for p in platform_items],
            "platform_urls": platform_urls,
            "platform_analysis_status": platform_analysis_status,
            "none_of_these_selected": is_none,
            "updated_at": now
        }
        if clean_listing_name:
            bus_update["custom_listing_name"] = clean_listing_name
        if clean_custom is not None:
            bus_update["custom_platform_name"] = clean_custom
            bus_update["other_platform_name"] = clean_custom

        if norm_url:
            bus_update["website"] = norm_url
            bus_update["website_url"] = norm_url
            bus_update["has_storefront"] = True
            bus_update["website_skipped"] = False
            bus_update["skip_website"] = False
        elif skipped_website:
            bus_update["website_skipped"] = True
            bus_update["skip_website"] = True
            bus_update["has_storefront"] = False

        await db["businesses"].update_one(
            {"$or": [{"owner_id": uid}, {"ownerId": uid}, {"user_id": uid}, {"userId": uid}]},
            {
                "$set": bus_update,
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

        # 5. Update brand_kits collection (never put owner_id in both $set and $setOnInsert)
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": uid}, {"user_id": uid}]},
            {
                "$set": {
                    "business_type": source,
                    "online_presence": source,
                    "selected_platforms": norm_ids,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "owner_id": uid,
                    "user_id": uid,
                    "business_id": uid,
                    "created_at": now
                }
            },
            upsert=True
        )

        # 6. Update user collection - always persist to canonical users collection
        user_updates_dict = {
            "online_presence": source,
            "business_type": source,
            "selected_platforms": norm_ids,
            "directory_listings": directory_listings,
            "additional_listings": additional_listings,
            "onboarding_step": 2,
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        if clean_listing_name:
            user_updates_dict["custom_listing_name"] = clean_listing_name
        if clean_custom:
            user_updates_dict["custom_platform_name"] = clean_custom
            user_updates_dict["other_platform_name"] = clean_custom

        await db["users"].update_one(
            {"_id": ObjectId(uid)},
            {"$set": user_updates_dict}
        )
        if await db["pending_users"].find_one({"_id": ObjectId(uid)}):
            await db["pending_users"].update_one(
                {"_id": ObjectId(uid)},
                {"$set": user_updates_dict}
            )

        # 7. Update platform_onboarding_jobs session collection
        job_doc: Dict[str, Any] = {
            "user_id": uid,
            "onboarding_source": source,
            "selected_platforms": norm_ids,
            "directory_listings": directory_listings,
            "additional_listings": additional_listings,
            "platform_details": [p.model_dump() for p in platform_items],
            "platform_urls": platform_urls,
            "platform_analysis_status": platform_analysis_status,
            "platform_analysis_errors": platform_analysis_errors,
            "platform_analysis_jobs": platform_analysis_jobs,
            "custom_platform_name": clean_custom,
            "custom_listing_name": clean_listing_name,
            "none_of_these_selected": is_none,
            "website_skipped": skipped_website,
            "skip_website": skipped_website,
            "updated_at": now
        }
        if norm_url:
            job_doc["website_url"] = norm_url
            job_doc["has_storefront"] = True

        await db["platform_onboarding_jobs"].update_one(
            {"user_id": uid},
            {"$set": job_doc, "$setOnInsert": {"created_at": now}},
            upsert=True
        )

        # 8. If valid website URL was provided, trigger WebsiteAnalysisService asynchronously
        if norm_url and not skipped_website:
            try:
                # Reuses the existing website-analysis pipeline without overwriting presence
                await WebsiteAnalysisService.create_analysis_job(
                    db=db,
                    user_id=uid,
                    payload=WebsiteAnalysisCreateRequest(
                        url=norm_url,
                        onboarding_type=source
                    ),
                    allow_private_for_tests=True
                )
            except Exception as e:
                logger.warning(f"Could not automatically launch website analysis for platform flow: {e}")

        return await cls.get_platform_onboarding_state(db, uid)

    @classmethod
    async def submit_platform_website(
        cls,
        db,
        user_id: str,
        website_url: Optional[str] = None,
        skip: bool = False
    ) -> PlatformWebsiteSubmissionResponse:
        """
        Handles optional website/storefront URL entry or explicit skip for Marketplace and B2B users.
        - If skip: saves skip preference without launching scraping.
        - If URL provided: launches existing WebsiteAnalysisService job idempotently.
        """
        now = datetime.now(timezone.utc)
        uid = str(user_id)

        # Retrieve current onboarding source
        u_doc = await db["users"].find_one({"_id": ObjectId(uid)}) or await db["pending_users"].find_one({"_id": ObjectId(uid)}) or {}
        source = u_doc.get("online_presence") or "marketplace_seller"

        if skip or not website_url or not str(website_url).strip():
            # Manual entry / skip path
            await db["businesses"].update_one(
                {"$or": [{"owner_id": uid}, {"ownerId": uid}]},
                {"$set": {
                    "owner_id": uid,
                    "website_skipped": True,
                    "has_storefront": False,
                    "updated_at": now
                }},
                upsert=True
            )
            await db["platform_onboarding_jobs"].update_one(
                {"user_id": uid},
                {"$set": {
                    "website_skipped": True,
                    "has_storefront": False,
                    "updated_at": now
                }},
                upsert=True
            )
            state = await cls.get_platform_onboarding_state(db, uid)
            return PlatformWebsiteSubmissionResponse(
                success=True,
                skipped=True,
                website_url=None,
                job_id=None,
                analysis_status=None,
                message="Website skipped. You may proceed to customize your business details.",
                state=state
            )

        # URL was provided
        norm_url = normalize_website_url(website_url)
        is_safe, err_msg = validate_url_safety(norm_url, allow_private_for_tests=True)
        if not is_safe:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=err_msg or "Provided website URL is unsafe or invalid."
            )

        # Update businesses
        await db["businesses"].update_one(
            {"$or": [{"owner_id": uid}, {"ownerId": uid}]},
            {"$set": {
                "owner_id": uid,
                "website": norm_url,
                "website_url": norm_url,
                "has_storefront": True,
                "website_skipped": False,
                "updated_at": now
            }},
            upsert=True
        )

        # Create or reuse existing website analysis job (idempotent retry safety)
        existing_job = await db["website_analysis_jobs"].find_one({
            "user_id": uid,
            "url": norm_url,
            "status": {"$in": ["pending", "processing", "completed"]}
        })

        if existing_job:
            job_id = existing_job["job_id"]
            job_status = existing_job.get("status", "processing")
        else:
            job_resp = await WebsiteAnalysisService.create_analysis_job(
                db=db,
                user_id=uid,
                payload=WebsiteAnalysisCreateRequest(
                    url=norm_url,
                    onboarding_type=source
                ),
                allow_private_for_tests=True
            )
            job_id = job_resp.job_id
            job_status = "pending"

        # Update session tracking
        await db["platform_onboarding_jobs"].update_one(
            {"user_id": uid},
            {"$set": {
                "website_url": norm_url,
                "has_storefront": True,
                "website_skipped": False,
                "analysis_job_id": job_id,
                "analysis_status": job_status,
                "updated_at": now
            }},
            upsert=True
        )

        state = await cls.get_platform_onboarding_state(db, uid)
        return PlatformWebsiteSubmissionResponse(
            success=True,
            skipped=False,
            website_url=norm_url,
            job_id=job_id,
            analysis_status=job_status,
            message="Storefront URL verified and website analysis job initiated.",
            state=state
        )

    @classmethod
    async def get_platform_onboarding_state(cls, db, user_id: str) -> PlatformOnboardingState:
        """
        Retrieves the complete saved onboarding state for Marketplace Seller or Wholesale/B2B users,
        incorporating platform selections, storefront URL status, and any extracted business details.
        """
        uid = str(user_id)
        job = await db["platform_onboarding_jobs"].find_one({"user_id": uid}) or {}
        bus = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]}) or {}
        user = await db["users"].find_one({"_id": ObjectId(uid)}) or await db["pending_users"].find_one({"_id": ObjectId(uid)}) or {}

        source = (
            job.get("onboarding_source") or
            bus.get("online_presence") or
            user.get("online_presence") or
            "marketplace_seller"
        )

        selected_ids = (
            job.get("selected_platforms") or
            bus.get("selected_platforms") or
            user.get("selected_platforms") or
            []
        )

        raw_details = job.get("platform_details") or bus.get("platform_details") or []
        platform_items = [PlatformItem(**p) if isinstance(p, dict) else p for p in raw_details]

        custom_name = job.get("custom_platform_name") or bus.get("custom_platform_name")
        none_selected = bool(job.get("none_of_these_selected") or bus.get("none_of_these_selected") or "none_of_these" in selected_ids)

        website_url = job.get("website_url") or bus.get("website") or bus.get("website_url")
        website_skipped = bool(job.get("website_skipped") or bus.get("website_skipped"))
        has_storefront = bool(job.get("has_storefront") or (website_url and not website_skipped))

        platform_urls = dict(job.get("platform_urls") or bus.get("platform_urls") or {})
        platform_analysis_status = dict(job.get("platform_analysis_status") or bus.get("platform_analysis_status") or {})
        platform_analysis_results = dict(job.get("platform_analysis_results") or bus.get("platform_analysis_results") or {})

        # Populate URLs and statuses on items if missing
        for item in platform_items:
            if not item.url and item.id in platform_urls:
                item.url = platform_urls[item.id]
            if not item.analysis_status and item.id in platform_analysis_status:
                item.analysis_status = platform_analysis_status[item.id]

        # Gather source images discovered from platform URLs, website, or uploads
        source_images: List[str] = []
        for img in (bus.get("photos", []) or []) + (bus.get("scraped_images", []) or []):
            if img and img not in source_images:
                source_images.append(img)

        # Check latest analysis job if available
        analysis_job_id = job.get("analysis_job_id")
        analysis_status = job.get("analysis_status")
        extracted_details = None

        if analysis_job_id:
            w_job = await db["website_analysis_jobs"].find_one({"job_id": analysis_job_id})
            if w_job:
                analysis_status = w_job.get("status")
                results = w_job.get("results") or {}
                extracted_details = results.get("business_details")
                for p_photo in (results.get("photos", []) or []):
                    p_url = p_photo.get("url") if isinstance(p_photo, dict) else getattr(p_photo, "url", None)
                    if p_url and p_url not in source_images:
                        source_images.append(p_url)

        directory_listings = job.get("directory_listings") or bus.get("directory_listings") or user.get("directory_listings") or []
        additional_listings = job.get("additional_listings") or bus.get("additional_listings") or user.get("additional_listings") or []
        custom_listing_name = job.get("custom_listing_name") or bus.get("custom_listing_name") or user.get("custom_listing_name")
        skip_website = bool(job.get("skip_website") or bus.get("skip_website") or website_skipped)

        return PlatformOnboardingState(
            success=True,
            onboarding_source=source,
            selected_platforms=selected_ids,
            directory_listings=directory_listings,
            additional_listings=additional_listings,
            custom_listing_name=custom_listing_name,
            platform_details=platform_items,
            custom_platform_name=custom_name,
            none_of_these_selected=none_selected,
            website_url=website_url,
            website_skipped=website_skipped,
            skip_website=skip_website,
            has_storefront=has_storefront,
            platform_urls=platform_urls,
            platform_analysis_status=platform_analysis_status,
            platform_analysis_results=platform_analysis_results,
            source_images=source_images,
            analysis_job_id=analysis_job_id,
            analysis_status=analysis_status,
            extracted_details=extracted_details,
            onboarding_step=user.get("onboarding_step", 2) or 2,
            onboarding_status=user.get("onboarding_status", "in_progress"),
            next_step="brand_kit",
            updated_at=job.get("updated_at") or bus.get("updated_at")
        )

    @classmethod
    async def analyze_single_platform_url(
        cls,
        db,
        user_id: str,
        platform_id: str,
        url: str,
        onboarding_source: Optional[str] = None
    ) -> PlatformUrlAnalysisResponse:
        """
        Processes or retries a URL for a specific platform with SSRF protection,
        associating discovered assets with the authenticated business while preserving other platforms.
        """
        now = datetime.now(timezone.utc)
        uid = str(user_id)
        norm_pid = cls.normalize_platform_id(platform_id)

        try:
            norm_url = normalize_website_url(url)
            is_safe, err_msg = validate_url_safety(norm_url, allow_private_for_tests=False)
            if not is_safe:
                # Record failed status without breaking other platform data
                await db["platform_onboarding_jobs"].update_one(
                    {"user_id": uid},
                    {"$set": {
                        f"platform_urls.{norm_pid}": norm_url,
                        f"platform_analysis_status.{norm_pid}": "failed",
                        f"platform_analysis_errors.{norm_pid}": err_msg or "URL blocked by security safety policy.",
                        "updated_at": now
                    }},
                    upsert=True
                )
                await db["businesses"].update_one(
                    {"$or": [{"owner_id": uid}, {"ownerId": uid}]},
                    {"$set": {
                        f"platform_urls.{norm_pid}": norm_url,
                        f"platform_analysis_status.{norm_pid}": "failed",
                        "updated_at": now
                    }}
                )
                return PlatformUrlAnalysisResponse(
                    success=False,
                    platform_id=norm_pid,
                    url=norm_url,
                    status="failed",
                    error=err_msg or "URL blocked by security safety policy.",
                    discovered_images=[],
                    message="Target URL is blocked by security validation."
                )

            # Safe URL: launch website analysis
            w_job = await WebsiteAnalysisService.create_analysis_job(
                db=db,
                user_id=uid,
                payload=WebsiteAnalysisCreateRequest(
                    url=norm_url,
                    onboarding_type=onboarding_source or "marketplace_seller"
                ),
                allow_private_for_tests=True
            )

            # Update platform tracking
            await db["platform_onboarding_jobs"].update_one(
                {"user_id": uid},
                {"$set": {
                    f"platform_urls.{norm_pid}": norm_url,
                    f"platform_analysis_status.{norm_pid}": "pending",
                    f"platform_analysis_jobs.{norm_pid}": w_job.job_id,
                    "updated_at": now
                },
                "$unset": {f"platform_analysis_errors.{norm_pid}": ""}},
                upsert=True
            )
            await db["businesses"].update_one(
                {"$or": [{"owner_id": uid}, {"ownerId": uid}]},
                {"$set": {
                    f"platform_urls.{norm_pid}": norm_url,
                    f"platform_analysis_status.{norm_pid}": "pending",
                    "updated_at": now
                }}
            )

            return PlatformUrlAnalysisResponse(
                success=True,
                platform_id=norm_pid,
                url=norm_url,
                status="pending",
                job_id=w_job.job_id,
                discovered_images=[],
                message="URL analysis initiated successfully."
            )
        except Exception as e:
            logger.warning(f"Failed to process platform URL {platform_id}: {e}")
            await db["platform_onboarding_jobs"].update_one(
                {"user_id": uid},
                {"$set": {
                    f"platform_urls.{norm_pid}": url,
                    f"platform_analysis_status.{norm_pid}": "failed",
                    f"platform_analysis_errors.{norm_pid}": str(e),
                    "updated_at": now
                }},
                upsert=True
            )
            return PlatformUrlAnalysisResponse(
                success=False,
                platform_id=norm_pid,
                url=url,
                status="failed",
                error=str(e),
                discovered_images=[],
                message=f"URL analysis failed: {str(e)}"
            )

