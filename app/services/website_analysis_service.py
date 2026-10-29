import asyncio
from collections import Counter
from datetime import datetime, timezone
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bson import ObjectId
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from fastapi import HTTPException, status
import httpx
from PIL import Image

from app.ai.factory import AIProviderFactory
from app.core.config import settings
from app.schemas.website_analysis import (
    ApplyWebsiteAnalysisResponse,
    BrandCategoryResult,
    BrandColorsResult,
    BrandPreferences,
    BrandVoiceResult,
    BusinessDetails,
    CompleteWebsiteOnboardingProfile,
    CompleteWebsiteOnboardingResponse,
    PhotoItem,
    StepStatuses,
    VALID_BRAND_TONES,
    VALID_BUSINESS_TYPES,
    VALID_CONTENT_LANGUAGES,
    WebsiteAnalysisCreateRequest,
    WebsiteAnalysisJobResponse,
    WebsiteAnalysisResults,
    WebsiteAnalysisStatusResponse,
    WebsitePhotoItem,
    WebsitePhotosResponse,
)
from app.services.onboarding_service import OnboardingService
from app.utils.url_validator import normalize_website_url, validate_url_safety, is_safe_redirect_target

logger = logging.getLogger(__name__)

# Maximum response size limit (5MB) to protect against memory exhaustion
MAX_HTML_BYTES = 5 * 1024 * 1024

# Common neutral hex colors to filter out when searching for brand colors
NEUTRAL_HEX_COLORS = {
    "#000000", "#FFFFFF", "#FFF", "#000",
    "#111111", "#121212", "#181818", "#1A1A1A", "#202020", "#212121", "#222222", "#2B2B2B", "#333333",
    "#444444", "#555555", "#666666", "#777777", "#888888", "#999999",
    "#AAAAAA", "#CCCCCC", "#DDDDDD", "#E0E0E0", "#E5E5E5", "#EEEEEE", "#F0F0F0", "#F4F4F4", "#F5F5F5",
    "#F8F9FA", "#FAFAFA", "#FCFCFC"
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
MAX_PHOTO_SELECTION = 10



def _get_image_signature(url: str) -> str:
    """Extracts a unique signature to deduplicate different sizes/params of the same photo."""
    try:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        if "_next/image" in parsed.path:
            qs = parse_qs(parsed.query)
            inner = qs.get("url")
            if inner and inner[0]:
                return inner[0].lower()
        clean_path = re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", parsed.path.lower())
        clean_path = re.sub(r"-scaled(?=\.[a-zA-Z]+$)", "", clean_path)
        return f"{parsed.netloc}{clean_path}"
    except Exception:
        return url.lower()


class WebsiteAnalysisService:
    """
    Comprehensive website crawling and AI brand extraction service.
    Orchestrates:
    - Real-time progress updates and fine-grained section statuses
    - SSRF protection and URL validation
    - Firecrawl JS rendering with resilient fallback to httpx + BeautifulSoup + JSON-LD
    - Dynamic extraction of every field from UI/UX reference screens:
      * Business Details: Business name, Category, Business types, Sub-category, City, Logo, Tagline, Who buys from you, Differentiators, Products/Services
      * Brand Preferences: Tagline card, 5 Brand colors, 16 Tones, 10 Languages, Target audience summary, Services/products summary
      * Website Photos: Real discovered images, selection limits, custom uploads
    - Multi-collection persistence across website_analysis_jobs, brand_kits, businesses, and users.
    """

    @classmethod
    async def create_analysis_job(
        cls,
        db,
        user_id: str,
        payload: WebsiteAnalysisCreateRequest,
        allow_private_for_tests: bool = False
    ) -> WebsiteAnalysisJobResponse:
        """
        Validates URL, enforces SSRF safety checks, initializes an analysis job in MongoDB,
        and launches the background extraction worker.
        """
        raw_url = payload.get_url()
        normalized_url = normalize_website_url(raw_url)

        # SSRF and DNS safety check
        is_safe, error_msg = validate_url_safety(normalized_url, allow_private_for_tests=allow_private_for_tests)
        if not is_safe:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg or "Target website URL is unsafe or invalid."
            )

        now = datetime.now(timezone.utc)
        import uuid
        job_id = f"job_{uuid.uuid4().hex[:16]}"

        job_doc = {
            "job_id": job_id,
            "user_id": str(user_id),
            "onboarding_type": payload.onboarding_type or "website",
            "url": normalized_url,
            "status": "pending",
            "progress": 0,
            "current_step": "initializing",
            "onboarding_step": "business_details",
            "step_statuses": {
                "fetching": "pending",
                "brand_voice": "pending",
                "colors": "pending",
                "category": "pending",
                "photos": "pending"
            },
            "results": None,
            "selected_photo_urls": [],
            "error": None,
            "created_at": now,
            "updated_at": now
        }

        await db["website_analysis_jobs"].insert_one(job_doc)

        # Determine target onboarding presence (preserve marketplace_seller / wholesale_b2b / google_maps)
        try:
            u_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) or await db["pending_users"].find_one({"_id": ObjectId(user_id)}) or {}
            existing_presence = u_doc.get("online_presence")
            NON_WEBSITE_PRESENCES = (
                "marketplace_seller", "marketplace",
                "wholesale_b2b", "wholesale", "b2b", "directories",
                "google_maps", "no_online_presence", "none",
                "social_media", "other", "something_else"
            )
            if payload.onboarding_type and payload.onboarding_type in NON_WEBSITE_PRESENCES:
                target_presence = payload.onboarding_type
            elif existing_presence in NON_WEBSITE_PRESENCES:
                target_presence = existing_presence

            # Update job doc to reflect target onboarding type
            await db["website_analysis_jobs"].update_one(
                {"job_id": job_id},
                {"$set": {"onboarding_type": target_presence}}
            )

            await OnboardingService.save_online_presence(
                db,
                user_id,
                {
                    "online_presence": target_presence,
                    "website_url": normalized_url,
                    "website": normalized_url,
                    "business_type": target_presence,
                    "business_name": payload.business_name
                }
            )
        except Exception as e:
            logger.warning(f"Could not automatically sync onboarding presence for job {job_id}: {e}")

        # Spawn asynchronous worker task
        asyncio.create_task(
            cls.run_analysis_pipeline(db, job_id, normalized_url, str(user_id))
        )

        return WebsiteAnalysisJobResponse(
            success=True,
            job_id=job_id,
            status="pending",
            url=normalized_url,
            onboarding_type=payload.onboarding_type or "website",
            created_at=now
        )

    @classmethod
    async def get_job_status(cls, db, job_id: str, user_id: str) -> WebsiteAnalysisStatusResponse:
        """
        Retrieves real-time status, progress, step statuses, and extracted results for a job.
        """
        doc = await db["website_analysis_jobs"].find_one({
            "job_id": job_id,
            "user_id": str(user_id)
        })

        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Website analysis job '{job_id}' not found."
            )

        doc.pop("_id", None)
        return WebsiteAnalysisStatusResponse(**doc)

    @classmethod
    async def get_latest_job(cls, db, user_id: str) -> Optional[WebsiteAnalysisStatusResponse]:
        """
        Retrieves the most recent analysis job for the current user to resume polling across refreshes.
        """
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            return None

        doc = docs[0]
        doc.pop("_id", None)
        return WebsiteAnalysisStatusResponse(**doc)

    @classmethod
    async def get_complete_profile(cls, db, user_id: str) -> CompleteWebsiteOnboardingProfile:
        """
        Returns the unified extracted profile (Business Details + Brand Preferences + Photos)
        for the user's active website onboarding session.
        """
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No website analysis found. Please submit your website URL first."
            )

        job = docs[0]
        results_data = job.get("results") or {}

        # Merge with any existing BrandKit and Business record in case user previously edited
        bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}
        kit_doc = await db["brand_kits"].find_one({"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]}) or {}

        # 1. Business details
        biz_details = results_data.get("business_details") or {}
        b_name = bus_doc.get("name") or bus_doc.get("business_name") or kit_doc.get("brand_name") or biz_details.get("business_name") or "My Business"
        category = bus_doc.get("category") or bus_doc.get("business_category") or kit_doc.get("business_category") or biz_details.get("category") or "General"
        sub_cat = bus_doc.get("sub_category") or kit_doc.get("sub_category") or biz_details.get("sub_category")
        city = bus_doc.get("city") or kit_doc.get("city") or biz_details.get("city")
        logo_url = bus_doc.get("logo_url") or kit_doc.get("logo_url") or biz_details.get("logo_url") or results_data.get("logo_url")
        tagline = bus_doc.get("tagline") or kit_doc.get("tagline") or biz_details.get("tagline")
        target_aud = bus_doc.get("target_customer") or kit_doc.get("target_audience") or biz_details.get("target_audience")
        b_types = bus_doc.get("business_types") or kit_doc.get("business_types") or biz_details.get("business_types") or ["Service / Digital"]
        pri_type = bus_doc.get("primary_business_type") or kit_doc.get("primary_business_type") or biz_details.get("primary_business_type") or (b_types[0] if b_types else "Service / Digital")
        diffs = bus_doc.get("differentiators") or kit_doc.get("differentiators") or biz_details.get("differentiators") or []
        prods = bus_doc.get("products_services") or kit_doc.get("products_services") or biz_details.get("products_services") or []

        business_details_model = BusinessDetails(
            business_name=b_name,
            category=category,
            business_types=b_types,
            primary_business_type=pri_type,
            sub_category=sub_cat,
            city=city,
            logo_url=logo_url,
            tagline=tagline,
            target_audience=target_aud,
            differentiators=diffs,
            products_services=prods
        )

        # 2. Brand preferences
        brand_prefs = results_data.get("brand_preferences") or {}
        colors = kit_doc.get("palette") or kit_doc.get("brand_colors") or bus_doc.get("brand_colors") or brand_prefs.get("brand_colors") or ["#FFFFFF", "#1E1E1E", "#E65100", "#2C2C2C", "#0A0A0A"]
        tones = kit_doc.get("tones") or bus_doc.get("tones") or brand_prefs.get("tones") or ["Modern", "Professional"]
        lang = kit_doc.get("language") or bus_doc.get("preferred_language") or brand_prefs.get("default_language") or "English"
        aud_summary = kit_doc.get("target_audience_summary") or brand_prefs.get("target_audience_summary") or target_aud
        prods_summary = kit_doc.get("services_products_summary") or brand_prefs.get("services_products_summary") or prods

        brand_preferences_model = BrandPreferences(
            tagline=tagline,
            brand_colors=colors[:5],
            tones=tones,
            default_language=lang,
            target_audience_summary=aud_summary,
            services_products_summary=prods_summary
        )

        # 3. Photos
        photos_raw = results_data.get("photos") or []
        photo_items = [WebsitePhotoItem(**p) if isinstance(p, dict) else p for p in photos_raw]
        selected_urls = job.get("selected_photo_urls") or kit_doc.get("selected_photos") or [p.url for p in photo_items[:4]]

        return CompleteWebsiteOnboardingProfile(
            success=True,
            job_id=job["job_id"],
            url=job["url"],
            status=job.get("status", "pending"),
            progress=job.get("progress", 0),
            current_step=job.get("current_step", "initializing"),
            onboarding_step=job.get("onboarding_step", "business_details"),
            step_statuses=StepStatuses(**job.get("step_statuses", {})),
            business_details=business_details_model,
            brand_preferences=brand_preferences_model,
            photos=photo_items,
            selected_photo_urls=selected_urls,
            created_at=job.get("created_at", datetime.now(timezone.utc)),
            updated_at=job.get("updated_at", datetime.now(timezone.utc))
        )

    @classmethod
    async def update_business_details(cls, db, user_id: str, details: BusinessDetails) -> CompleteWebsiteOnboardingProfile:
        """
        Saves user edits from Screen 1-3 ("Is this your business?") and advances onboarding step to 'brand_preferences'.
        """
        now = datetime.now(timezone.utc)
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Website analysis job not found.")

        job_id = docs[0]["job_id"]

        # Update in website_analysis_jobs
        await db["website_analysis_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {
                "results.business_details": details.model_dump(),
                "onboarding_step": "brand_preferences",
                "updated_at": now
            }}
        )

        # Update in businesses collection
        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {
                "$set": {
                    "owner_id": str(user_id),
                    "ownerId": str(user_id),
                    "user_id": str(user_id),
                    "name": details.business_name,
                    "business_name": details.business_name,
                    "category": details.category,
                    "business_category": details.category,
                    "sub_category": details.sub_category,
                    "city": details.city,
                    "logo_url": details.logo_url,
                    "tagline": details.tagline,
                    "target_customer": details.target_audience,
                    "business_types": details.business_types,
                    "primary_business_type": details.primary_business_type,
                    "differentiators": details.differentiators,
                    "products_services": details.products_services,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "location": "India",
                    "created_at": now
                }
            },
            upsert=True
        )

        # Update in brand_kits collection
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {
                "$set": {
                    "business_id": str(user_id),
                    "owner_id": str(user_id),
                    "user_id": str(user_id),
                    "brand_name": details.business_name,
                    "business_name": details.business_name,
                    "business_category": details.category,
                    "sub_category": details.sub_category,
                    "city": details.city,
                "logo_url": details.logo_url,
                "tagline": details.tagline,
                "target_audience": details.target_audience,
                "business_types": details.business_types,
                "primary_business_type": details.primary_business_type,
                "differentiators": details.differentiators,
                "products_services": details.products_services,
                "updated_at": now
            }},
            upsert=True
        )

        return await cls.get_complete_profile(db, user_id)

    @classmethod
    async def update_brand_preferences(cls, db, user_id: str, prefs: BrandPreferences) -> CompleteWebsiteOnboardingProfile:
        """
        Saves user edits from Screen 4-5 ("What's your business like?") and advances onboarding step to 'website_photos'.
        """
        now = datetime.now(timezone.utc)
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Website analysis job not found.")

        job_id = docs[0]["job_id"]

        # Validate tone options
        validated_tones = [t for t in prefs.tones if t in VALID_BRAND_TONES] or prefs.tones[:4]

        # Update in website_analysis_jobs
        await db["website_analysis_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {
                "results.brand_preferences": prefs.model_dump(),
                "onboarding_step": "website_photos",
                "updated_at": now
            }}
        )

        # Update in businesses collection
        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {
                "$set": {
                    "owner_id": str(user_id),
                    "ownerId": str(user_id),
                    "user_id": str(user_id),
                    "brand_colors": prefs.brand_colors[:5],
                    "tones": validated_tones,
                    "preferred_language": prefs.default_language,
                    "tagline": prefs.tagline,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "name": "My Business",
                    "business_name": "My Business",
                    "location": "India",
                    "created_at": now
                }
            },
            upsert=True
        )

        # Update in brand_kits collection
        primary_col = prefs.brand_colors[0] if len(prefs.brand_colors) > 0 else "#FFFFFF"
        secondary_col = prefs.brand_colors[1] if len(prefs.brand_colors) > 1 else "#1E1E1E"
        accent_col = prefs.brand_colors[2] if len(prefs.brand_colors) > 2 else "#E65100"

        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {
                "$set": {
                    "business_id": str(user_id),
                    "owner_id": str(user_id),
                    "user_id": str(user_id),
                    "tagline": prefs.tagline,
                    "primary_color": primary_col,
                    "secondary_color": secondary_col,
                    "accent_color": accent_col,
                    "palette": prefs.brand_colors[:5],
                    "brand_colors": prefs.brand_colors[:5],
                "tones": validated_tones,
                "brand_voice": ", ".join(validated_tones),
                "language": prefs.default_language,
                "target_audience_summary": prefs.target_audience_summary,
                "services_products_summary": prefs.services_products_summary,
                "updated_at": now
            }},
            upsert=True
        )

        return await cls.get_complete_profile(db, user_id)

    @classmethod
    async def get_website_photos(cls, db, user_id: str) -> WebsitePhotosResponse:
        """
        Retrieves discovered images from the scraped website and the user's selected list.
        """
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Website analysis job not found.")

        job = docs[0]
        results = job.get("results") or {}
        photos_raw = results.get("photos") or []
        selected_urls = job.get("selected_photo_urls") or []

        photo_items: List[WebsitePhotoItem] = []
        for p in photos_raw:
            item = WebsitePhotoItem(**p) if isinstance(p, dict) else p
            item.selected = (item.url in selected_urls)
            photo_items.append(item)

        return WebsitePhotosResponse(
            success=True,
            job_id=job["job_id"],
            photos=photo_items,
            selected_photo_urls=selected_urls,
            max_selection_limit=MAX_PHOTO_SELECTION,
            total_discovered=len(photo_items),
            selected_count=len(selected_urls)
        )

    @classmethod
    async def save_selected_photos(cls, db, user_id: str, selected_urls: List[str]) -> WebsitePhotosResponse:
        """
        Saves selected photo URLs and enforces maximum selection limit.
        """
        if len(selected_urls) > MAX_PHOTO_SELECTION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You can select a maximum of {MAX_PHOTO_SELECTION} photos."
            )

        now = datetime.now(timezone.utc)
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(status_code=404, detail="Website analysis job not found.")

        job_id = docs[0]["job_id"]

        # Update in website_analysis_jobs
        await db["website_analysis_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {
                "selected_photo_urls": selected_urls,
                "updated_at": now
            }}
        )

        # Update in businesses and brand_kits
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": {"owner_id": str(user_id), "selected_photos": selected_urls, "updated_at": now}},
            upsert=True
        )
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": {"business_id": str(user_id), "owner_id": str(user_id), "selected_photos": selected_urls, "updated_at": now}},
            upsert=True
        )

        return await cls.get_website_photos(db, user_id)

    @classmethod
    async def upload_user_photo(
        cls,
        db,
        user_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> WebsitePhotoItem:
        """
        Validates, securely stores, and adds a user-uploaded image to the website photos catalog.
        """
        # Validate file size (10 MB max)
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file exceeds 10 MB size limit."
            )

        # Validate image integrity via Pillow
        width = None
        height = None
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
            width, height = img.size
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image file: {str(e)}"
            )

        # Safe filename generation
        import uuid
        safe_ext = os.path.splitext(filename)[1].lower()
        if safe_ext not in [".jpg", ".jpeg", ".png", ".webp", ".svg"]:
            safe_ext = ".jpg"

        upload_dir = os.path.join("uploads", "onboarding_photos")
        os.makedirs(upload_dir, exist_ok=True)
        unique_name = f"{user_id}_{uuid.uuid4().hex[:12]}{safe_ext}"
        target_path = os.path.join(upload_dir, unique_name)

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        public_url = settings.get_public_url(f"/uploads/onboarding_photos/{unique_name}")

        new_photo = WebsitePhotoItem(
            url=public_url,
            alt=os.path.splitext(filename)[0] or "Uploaded Image",
            type="user_upload",
            width=width,
            height=height,
            source_page="user_upload",
            selected=True
        )

        # Append to job's photo list
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if docs:
            job_id = docs[0]["job_id"]
            await db["website_analysis_jobs"].update_one(
                {"job_id": job_id},
                {
                    "$push": {"results.photos": new_photo.model_dump()},
                    "$addToSet": {"selected_photo_urls": public_url},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                }
            )

        return new_photo

    @classmethod
    async def complete_website_onboarding(cls, db, user_id: str) -> CompleteWebsiteOnboardingResponse:
        """
        Finalizes website onboarding steps and advances the user's stepper to step 3 (Social Connectivity).
        """
        now = datetime.now(timezone.utc)
        cursor = db["website_analysis_jobs"].find({"user_id": str(user_id)}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        if not docs:
            raise HTTPException(status_code=404, detail="No website analysis job found.")

        job = docs[0]
        job_id = job["job_id"]

        # Mark job as completed
        await db["website_analysis_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {
                "onboarding_step": "completed",
                "updated_at": now
            }}
        )

        # Advance user onboarding step to 3 (Social Connectivity), preserving specific online_presence
        u_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) or await db["pending_users"].find_one({"_id": ObjectId(user_id)}) or {}
        NON_WEBSITE_PRESENCES = (
            "marketplace_seller", "marketplace",
            "wholesale_b2b", "wholesale", "b2b", "directories",
            "google_maps", "no_online_presence", "none",
            "social_media", "other", "something_else"
        )
        if user_presence not in NON_WEBSITE_PRESENCES:
            user_presence = u_doc.get("online_presence") or "website"

        # Always update canonical users collection
        user_updates_map = {
            "onboarding_step": 3,
            "online_presence": user_presence,
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        await db["users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": user_updates_map}
        )
        if await db["pending_users"].find_one({"_id": ObjectId(user_id)}):
            await db["pending_users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_updates_map}
            )

        refreshed_kit = await db["brand_kits"].find_one({"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]}) or {}
        refreshed_bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}
        refreshed_kit.pop("_id", None)
        refreshed_bus.pop("_id", None)

        return CompleteWebsiteOnboardingResponse(
            success=True,
            message="Website onboarding completed successfully. Proceed to Social Media Connectivity.",
            job_id=job_id,
            next_step="social_connectivity",
            onboarding_route="/onboarding?step=social_connectivity",
            business=refreshed_bus,
            brand_kit=refreshed_kit
        )

    # -------------------------------------------------------------------------
    # Core Extraction Pipeline (Firecrawl -> httpx -> bs4 -> Gemini AI)
    # -------------------------------------------------------------------------

    @classmethod
    async def run_analysis_pipeline(cls, db, job_id: str, url: str, user_id: str) -> None:
        """
        Core async pipeline for fetching HTML, parsing assets, calling Gemini AI for brand extraction,
        and persisting results with fine-grained step-by-step progress tracking.
        """
        logger.info(f"Starting website analysis pipeline for job {job_id} ({url})")
        now = datetime.now(timezone.utc)

        # 1. Transition to processing
        await cls._update_job(
            db, job_id,
            status="processing",
            progress=15,
            current_step="fetching_website",
            step_statuses_update={"fetching": "in_progress"}
        )

        # 2. Fetch Website HTML (Firecrawl JS rendering or httpx with retry)
        html_content, final_url, fetch_error = await cls._fetch_website(url)
        if fetch_error or not html_content:
            err_msg = fetch_error or "Failed to download website content."
            logger.error(f"Job {job_id} fetching failed: {err_msg}")
            await cls._update_job(
                db, job_id,
                status="failed",
                progress=0,
                current_step="failed",
                error=err_msg,
                step_statuses_update={"fetching": "failed"}
            )
            return

        await cls._update_job(
            db, job_id,
            progress=30,
            current_step="extracting_assets",
            step_statuses_update={"fetching": "completed"}
        )

        # 3. Extract metadata, colors, images, and text content
        extracted = cls._parse_html_content(html_content, final_url or url)

        # 4. Step-by-step Dynamic Analysis via Gemini
        await cls._update_job(
            db, job_id,
            progress=45,
            current_step="analyzing_brand_voice",
            step_statuses_update={"brand_voice": "in_progress"}
        )

        await cls._update_job(
            db, job_id,
            progress=60,
            current_step="analyzing_category",
            step_statuses_update={"category": "in_progress"}
        )

        await cls._update_job(
            db, job_id,
            progress=75,
            current_step="analyzing_colors",
            step_statuses_update={"colors": "in_progress"}
        )

        await cls._update_job(
            db, job_id,
            progress=85,
            current_step="analyzing_photos",
            step_statuses_update={"photos": "in_progress"}
        )

        # Perform AI Extraction
        try:
            ai_results = await cls._execute_ai_analysis(extracted, final_url or url)
        except Exception as e:
            logger.error(f"AI brand analysis failed for job {job_id}: {e}", exc_info=True)
            ai_results = cls._build_heuristic_fallback(extracted, final_url or url)

        # 5. Finalize Results
        results_model = WebsiteAnalysisResults(
            brand_voice=ai_results.get("brand_voice"),
            colors=ai_results.get("colors"),
            category=ai_results.get("category"),
            photos=ai_results.get("photos", []),
            logo_url=ai_results.get("logo_url") or extracted.get("logo_candidate"),
            hero_image=ai_results.get("hero_image") or extracted.get("hero_candidate"),
            website_title=extracted.get("title"),
            meta_description=extracted.get("description"),
            business_details=ai_results.get("business_details"),
            brand_preferences=ai_results.get("brand_preferences")
        )

        initial_selected_photos = [p.url for p in results_model.photos[:4]]

        await cls._update_job(
            db, job_id,
            status="completed",
            progress=100,
            current_step="completed",
            onboarding_step="business_details",
            step_statuses_update={
                "fetching": "completed",
                "brand_voice": "completed",
                "colors": "completed",
                "category": "completed",
                "photos": "completed"
            },
            results=results_model.model_dump(),
            extra_updates={"selected_photo_urls": initial_selected_photos}
        )

        # Pre-populate Brand Kit and Business document
        try:
            await cls._sync_results_to_profile(db, user_id, results_model, final_url or url)
        except Exception as e:
            logger.warning(f"Could not auto-sync analysis to profile for job {job_id}: {e}")

        logger.info(f"Website analysis job {job_id} successfully completed.")

    @classmethod
    async def apply_analysis_to_profile(cls, db, job_id: str, user_id: str) -> ApplyWebsiteAnalysisResponse:
        """
        Applies analyzed brand voice, colors, category, and photos directly to the user's
        persistent Brand Kit and business records.
        """
        job = await db["website_analysis_jobs"].find_one({
            "job_id": job_id,
            "user_id": str(user_id)
        })

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Website analysis job '{job_id}' not found."
            )

        if job.get("status") != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot apply analysis: job status is currently '{job.get('status')}'."
            )

        results = job.get("results")
        if not results:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No analysis results available to apply."
            )

        results_model = WebsiteAnalysisResults(**results)
        brand_kit_doc, bus_doc = await cls._sync_results_to_profile(db, user_id, results_model, job.get("url"))

        return ApplyWebsiteAnalysisResponse(
            success=True,
            message="Website analysis successfully applied to brand kit and profile.",
            job_id=job_id,
            brand_kit=brand_kit_doc,
            business=bus_doc
        )

    # -------------------------------------------------------------------------
    # Internal Helpers: HTTP Fetching, HTML Parsing, AI Generation, Persistence
    # -------------------------------------------------------------------------

    @classmethod
    async def _fetch_website(cls, url: str, allow_private_for_tests: bool = False) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Fetches website HTML safely:
        - Validates every redirect target against SSRF (rejects private/internal IPs).
        - Enforces response size limit (5MB max).
        - Enforces 15s timeout and handles connection/HTTP errors gracefully.
        Returns: (html_text, final_url, error_message)
        """
        # Try Firecrawl for JavaScript-rendered sites if FIRECRAWL_API_KEY is available
        if getattr(settings, "FIRECRAWL_API_KEY", None):
            try:
                from firecrawl import FirecrawlApp
                firecrawl_client = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
                scrape_res = firecrawl_client.scrape_url(url, params={"formats": ["html", "markdown"]})
                if scrape_res and isinstance(scrape_res, dict) and scrape_res.get("html"):
                    logger.info(f"Successfully scraped JS-rendered website via Firecrawl for {url}")
                    return scrape_res["html"], url, None
            except Exception as e:
                logger.warning(f"Firecrawl scrape failed or unconfigured ({e}). Falling back to native httpx extraction.")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        }

        for attempt in range(2):
            try:
                current_url = url
                final_url = current_url

                async with httpx.AsyncClient(
                    timeout=15.0,
                    follow_redirects=False,
                    verify=True
                ) as client:
                    for _ in range(5):
                        # Ensure current URL is safe before fetching
                        is_safe, error_msg = validate_url_safety(current_url, allow_private_for_tests=allow_private_for_tests)
                        if not is_safe:
                            return None, None, f"Destination blocked for security: {error_msg}"

                        resp = await client.get(current_url, headers=headers)

                        # Handle redirects safely
                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("Location")
                            if not loc:
                                return None, None, f"Website returned redirect HTTP {resp.status_code} without Location header."
                            next_raw = urljoin(current_url, loc.strip())
                            is_safe_red, next_norm, red_err = is_safe_redirect_target(next_raw, allow_private_for_tests=allow_private_for_tests)
                            if not is_safe_red or not next_norm:
                                return None, None, f"Unsafe redirect destination blocked: {red_err or 'Access to internal address prohibited'}"
                            current_url = next_norm
                            continue

                        final_url = current_url
                        if resp.status_code == 200:
                            content_bytes = resp.content
                            if len(content_bytes) > MAX_HTML_BYTES:
                                content_bytes = content_bytes[:MAX_HTML_BYTES]
                            html_text = content_bytes.decode(resp.encoding or "utf-8", errors="replace")
                            return html_text, str(final_url), None
                        elif resp.status_code == 404:
                            return None, None, f"Website returned 404 Not Found at '{current_url}'. Please check that the URL is active."
                        elif resp.status_code in (401, 403):
                            return None, None, f"Website returned HTTP {resp.status_code} Access Denied. The website may have bot protection enabled."
                        elif resp.status_code >= 500:
                            if attempt == 0:
                                await asyncio.sleep(1.0)
                                break
                            return None, None, f"Target website server encountered an error (HTTP {resp.status_code})."
                        else:
                            return None, None, f"Unexpected response from website (HTTP {resp.status_code})."

                    return None, None, "Website exceeded maximum allowed redirects (5)."

            except httpx.ConnectTimeout:
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                return None, None, f"Connection to website '{url}' timed out after 15 seconds. Please ensure the server is responsive."
            except httpx.ConnectError:
                return None, None, f"Could not establish a connection to '{url}'. Please check domain name and server status."
            except httpx.RequestError as e:
                return None, None, f"Network error while accessing website: {str(e)}"
            except Exception as e:
                return None, None, f"Failed to fetch website: {str(e)}"

        return None, None, "Website fetch failed after retry."


    @classmethod
    def _parse_html_content(cls, html: str, base_url: str) -> Dict[str, Any]:
        """
        Extracts structural text, metadata, CSS colors, JSON-LD structured data, and images from HTML.
        """
        if BeautifulSoup is None:
            logger.warning("beautifulsoup4 is not installed. Using regex HTML parsing fallback. Run `pip install beautifulsoup4`.")
            return cls._parse_html_fallback(html, base_url)

        soup = BeautifulSoup(html, "html.parser")

        # 1. Page Title & Meta
        raw_title = ""
        if soup.title and soup.title.string:
            raw_title = soup.title.string.strip()
        og_title = soup.find("meta", property="og:title")
        if not raw_title and og_title and og_title.get("content"):
            raw_title = og_title["content"].strip()

        # Clean title for clean business name candidate (e.g. "Aurora Luxe | Sustainable Fashion" -> "Aurora Luxe")
        clean_title = re.split(r"\s+[|\-–—:•]\s+", raw_title)[0].strip() if raw_title else ""
        title = raw_title or clean_title

        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()

        site_name = ""
        meta_site = soup.find("meta", property="og:site_name") or soup.find("meta", attrs={"name": "application-name"})
        if meta_site and meta_site.get("content"):
            site_name = meta_site["content"].strip()

        # Favicon / Apple Touch Icon / Explicit Logo Meta
        meta_logo_url = None
        for meta in soup.find_all("meta"):
            p_val = (meta.get("property") or meta.get("name") or "").strip().lower()
            if p_val in ["og:logo", "logo"] and meta.get("content"):
                meta_logo_url = urljoin(base_url, meta["content"].strip())
                break

        apple_icon_url = None
        favicon_url = None
        for link in soup.find_all("link"):
            rel_val = link.get("rel") or []
            rel_list = rel_val if isinstance(rel_val, list) else [rel_val]
            rel_str = " ".join([str(x).lower() for x in rel_list])
            if not apple_icon_url and "apple-touch-icon" in rel_str and link.get("href"):
                apple_icon_url = urljoin(base_url, link["href"].strip())
            if not favicon_url and any(x in rel_str for x in ["icon", "shortcut icon"]) and link.get("href"):
                favicon_url = urljoin(base_url, link["href"].strip())

        # 2. JSON-LD Structured Data Parsing
        ld_name = None
        ld_city = None
        ld_tagline = None
        ld_category = None
        ld_products: List[str] = []
        ld_logo = meta_logo_url or apple_icon_url

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw_json = script.string or script.get_text()
                if not raw_json:
                    continue
                data = json.loads(raw_json)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_type = str(item.get("@type", "")).lower()
                    if any(t in item_type for t in ["organization", "localbusiness", "store", "corporation", "company", "clothingstore", "restaurant", "health"]):
                        if not ld_name and item.get("name"):
                            ld_name = str(item["name"]).strip()
                        if not ld_logo and item.get("logo"):
                            logo_val = item["logo"]
                            if isinstance(logo_val, dict) and logo_val.get("url"):
                                ld_logo = urljoin(base_url, str(logo_val["url"]).strip())
                            elif isinstance(logo_val, str):
                                ld_logo = urljoin(base_url, logo_val.strip())
                        if not ld_tagline and item.get("slogan"):
                            ld_tagline = item["slogan"]
                        if not ld_category:
                            if any(k in item_type for k in ["restaurant", "food", "cafe"]):
                                ld_category = "Food & Beverage"
                            elif any(k in item_type for k in ["clothing", "apparel", "fashion"]):
                                ld_category = "Fashion & Apparel"
                            elif any(k in item_type for k in ["health", "medical"]):
                                ld_category = "Health & Wellness"
                            elif any(k in item_type for k in ["tech", "software"]):
                                ld_category = "Technology & IT"
                        if not ld_city and item.get("address"):
                            addr = item["address"]
                            if isinstance(addr, dict):
                                loc = addr.get("addressLocality")
                                country = addr.get("addressCountry")
                                if loc and country:
                                    ld_city = f"{loc}, {country}"
                                elif loc:
                                    ld_city = loc

                            if isinstance(addr, dict):
                                loc = addr.get("addressLocality")
                                country = addr.get("addressCountry")
                                if loc and country:
                                    ld_city = f"{loc}, {country}"
                                elif loc:
                                    ld_city = loc
                    # Check for products/services
                    if "product" in item_type or "service" in item_type:
                        if item.get("name"):
                            ld_products.append(item["name"])
            except Exception:
                continue

        # 3. Location / City Heuristics (Footer address, meta tags)
        city_candidate = ld_city
        if not city_candidate:
            geo_meta = soup.find("meta", attrs={"name": "geo.placename"})
            if geo_meta and geo_meta.get("content"):
                city_candidate = geo_meta["content"].strip()

        if not city_candidate:
            address_tag = soup.find("address")
            if address_tag:
                addr_text = address_tag.get_text(separator=" ", strip=True)
                # Look for common Indian and international cities
                city_match = re.search(r"\b(Jaipur|Mumbai|Delhi|Bengaluru|Bangalore|Pune|Hyderabad|Chennai|Kolkata|Ahmedabad|Noida|Gurgaon|Surat|Indore|Chandigarh|New York|London|Dubai|Singapore)\b", addr_text, re.IGNORECASE)
                if city_match:
                    city_candidate = f"{city_match.group(1).title()}, India" if city_match.group(1).lower() in ["jaipur", "mumbai", "delhi", "bengaluru", "bangalore", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad", "noida", "gurgaon", "surat", "indore", "chandigarh"] else city_match.group(1).title()

        # 4. CSS Hex Colors Extraction
        theme_colors = []
        theme_meta = soup.find("meta", attrs={"name": "theme-color"})
        if theme_meta and theme_meta.get("content"):
            t_color = theme_meta["content"].strip().upper()
            if re.match(r"^#[0-9A-F]{6}$", t_color):
                theme_colors.append(t_color)

        raw_styles = " ".join([tag.get_text() for tag in soup.find_all("style")])
        for tag in soup.find_all(True, style=True):
            raw_styles += " " + tag["style"]

        hex_matches = re.findall(r"#[0-9a-fA-F]{6}\b", raw_styles)
        color_counts = Counter([c.upper() for c in hex_matches if c.upper() not in NEUTRAL_HEX_COLORS])
        top_css_colors = [c for c, _ in color_counts.most_common(8)]
        if theme_colors:
            top_css_colors = theme_colors + [c for c in top_css_colors if c not in theme_colors]

        # 5. Photos & Images Extraction (Robust, Dynamic Multi-Source Discovery)
        photos: List[WebsitePhotoItem] = []
        seen_sigs = set()
        logo_candidate = ld_logo
        hero_candidate = None

        def add_photo(raw_url: Optional[str], p_type: str, alt: str = "") -> None:
            nonlocal logo_candidate, hero_candidate
            if not raw_url:
                return
            candidates = []
            if "," in raw_url and (" " in raw_url or "w" in raw_url):
                # For srcset, take the highest resolution entry (usually last)
                parts = [p.strip().split(" ")[0] for p in raw_url.split(",") if p.strip()]
                if parts:
                    candidates.append(parts[-1])
            else:
                candidates.append(raw_url.strip())

            for cand in candidates:
                cand = cand.strip()
                if not cand or cand.startswith("data:") or "pixel" in cand.lower() or "beacon" in cand.lower():
                    continue
                full = urljoin(base_url, cand)
                if not full.startswith("http"):
                    continue
                lower_full = full.lower()
                # Filter out obvious tiny UI icons / social icons / tracker scripts
                if any(junk in lower_full for junk in [
                    "1x1", "spacer", "facebook.svg", "twitter.svg", "linkedin.svg",
                    "instagram.svg", "youtube.svg", "chevron", "caret", "arrow-",
                    "favicon.ico", "cart-icon", "search-icon", "close-icon", "spinner", "loader"
                ]):
                    continue

                sig = _get_image_signature(full)
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    is_logo = (p_type == "logo") or ("logo" in lower_full) or ("logo" in alt.lower())
                    is_hero = (p_type == "hero") or ("hero" in lower_full) or ("banner" in lower_full) or ("slider" in lower_full)
                    classified_type = "logo" if is_logo else ("hero" if is_hero else "product")

                    if is_logo and not logo_candidate:
                        logo_candidate = full
                    if is_hero and not hero_candidate:
                        hero_candidate = full

                    photos.append(WebsitePhotoItem(
                        url=full,
                        type=classified_type,
                        alt=alt or f"Extracted {classified_type.title()}",
                        selected=(len(photos) < 6)
                    ))

        # 5.1 OpenGraph & Twitter Images
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "") or meta.get("name", "")
            if prop in ["og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"]:
                add_photo(meta.get("content"), "hero", "Cover / Hero Image")

        # 5.2 JSON-LD Schema.org Images
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw_json = script.string or script.get_text()
                if not raw_json:
                    continue
                data = json.loads(raw_json)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        imgs = item.get("image") or item.get("images")
                        if isinstance(imgs, str):
                            add_photo(imgs, "product", item.get("name", "Product Image"))
                        elif isinstance(imgs, list):
                            for im in imgs:
                                if isinstance(im, str):
                                    add_photo(im, "product", item.get("name", "Product Image"))
                                elif isinstance(im, dict) and im.get("url"):
                                    add_photo(im["url"], "product", item.get("name", "Product Image"))
            except Exception:
                pass

        # 5.3 <img> Tags (src, data-src, data-original, data-lazy-src, srcset, data-srcset)
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy-src")
            alt = (img.get("alt") or "").strip()
            class_and_id = f"{img.get('class', '')} {img.get('id', '')}".lower()
            is_logo = "logo" in class_and_id or "logo" in (src or "").lower() or "brand" in class_and_id
            is_hero = "hero" in class_and_id or "banner" in class_and_id or "slider" in class_and_id
            p_type = "logo" if is_logo else ("hero" if is_hero else "product")

            srcset = img.get("srcset") or img.get("data-srcset")
            if srcset:
                add_photo(srcset, p_type, alt)
            elif src:
                add_photo(src, p_type, alt)

        # 5.4 <picture> <source> Tags
        for source in soup.find_all("source"):
            srcset = source.get("srcset") or source.get("data-srcset")
            if srcset:
                add_photo(srcset, "gallery", "Website Photo")

        # 5.5 Inline CSS Background Images
        for tag in soup.find_all(True, style=True):
            style = tag.get("style", "")
            bg_matches = re.findall(r"url\([\'\"]?(https?://[^\'\")]+|[^\'\")]+)[\'\"]?\)", style)
            for bg in bg_matches:
                if not bg.endswith(".css") and not bg.endswith(".js"):
                    add_photo(bg, "hero", "Banner Photo")

        if not logo_candidate and favicon_url:
            logo_candidate = favicon_url

        # 6. Text Content (H1, H2, H3, paragraphs)
        for junk in soup(["script", "style", "noscript", "iframe", "svg"]):
            junk.decompose()

        headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)]
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]

        extracted_text = " | ".join(headings[:8]) + "\n" + " ".join(paragraphs[:10])
        extracted_text = re.sub(r"\s+", " ", extracted_text).strip()[:4000]

        # 7. Phone & Contact extraction heuristic
        phone_candidate = None
        tel_link = soup.find("a", href=lambda h: h and str(h).startswith("tel:"))
        if tel_link and tel_link.get("href"):
            phone_candidate = str(tel_link["href"]).replace("tel:", "").strip()
        if not phone_candidate:
            body_sample = soup.body.get_text(separator=" ", strip=True) if soup.body else extracted_text
            m_phone = re.search(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,6}", body_sample)
            if m_phone:
                p_cand = m_phone.group(0).strip()
                if sum(c.isdigit() for c in p_cand) >= 7:
                    phone_candidate = p_cand

        parsed_domain = urlparse(base_url).netloc.replace("www.", "")

        return {
            "title": title or parsed_domain.title(),
            "clean_title": clean_title or title or parsed_domain.title(),
            "description": description or f"Official website of {parsed_domain.title()}",
            "site_name": site_name or ld_name or clean_title or parsed_domain.title(),
            "domain": parsed_domain,
            "top_css_colors": top_css_colors,
            "photos": photos,
            "logo_candidate": logo_candidate,
            "hero_candidate": hero_candidate,
            "body_text": extracted_text,
            "ld_name": ld_name,
            "ld_city": city_candidate,
            "ld_tagline": ld_tagline,
            "ld_category": ld_category,
            "ld_products": ld_products,
            "phone": phone_candidate,
            "phone_number": phone_candidate
        }


    @classmethod
    def _parse_html_fallback(cls, html: str, base_url: str) -> Dict[str, Any]:
        """
        Lightweight fallback HTML parser using regex when beautifulsoup4 is missing.
        Ensures the application never crashes on startup or basic extraction.
        """
        # 1. Page Title & Meta
        title = ""
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m_title:
            title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip()

        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if not title and og_title:
            title = og_title.group(1).strip()

        description = ""
        m_desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_desc:
            description = m_desc.group(1).strip()

        site_name = ""
        m_site = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_site:
            site_name = m_site.group(1).strip()

        # Favicon / Icons
        favicon_url = None
        m_icon = re.search(r'<link[^>]+rel=["\'][^"\']*(?:icon|shortcut icon|apple-touch-icon)[^"\']*["\'][^>]+href=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_icon:
            favicon_url = urljoin(base_url, m_icon.group(1).strip())

        # CSS Hex Colors
        theme_colors = []
        m_theme = re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\'](#[0-9a-fA-F]{6})["\']', html, re.IGNORECASE)
        if m_theme:
            theme_colors.append(m_theme.group(1).upper())

        hex_matches = re.findall(r"#[0-9a-fA-F]{6}\b", html)
        color_counts = Counter([c.upper() for c in hex_matches if c.upper() not in NEUTRAL_HEX_COLORS])
        top_css_colors = [c for c, _ in color_counts.most_common(8)]
        if theme_colors:
            top_css_colors = theme_colors + [c for c in top_css_colors if c not in theme_colors]

        # Photos
        photos: List[WebsitePhotoItem] = []
        seen_sigs = set()
        logo_candidate = favicon_url
        hero_candidate = None

        def add_photo(raw_url: Optional[str], p_type: str, alt: str = "") -> None:
            nonlocal logo_candidate, hero_candidate
            if not raw_url:
                return
            clean_url = raw_url.strip()
            if not clean_url or clean_url.startswith("data:") or "pixel" in clean_url.lower():
                return
            full = urljoin(base_url, clean_url)
            if not full.startswith("http"):
                return
            lower_full = full.lower()
            if any(junk in lower_full for junk in ["1x1", "spacer", "chevron", "arrow-", "favicon.ico", "spinner", "loader"]):
                return
            sig = _get_image_signature(full)
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                is_logo = (p_type == "logo") or ("logo" in lower_full) or ("logo" in alt.lower())
                is_hero = (p_type == "hero") or ("hero" in lower_full) or ("banner" in lower_full)
                classified_type = "logo" if is_logo else ("hero" if is_hero else "product")
                if is_logo and not logo_candidate:
                    logo_candidate = full
                if is_hero and not hero_candidate:
                    hero_candidate = full
                photos.append(WebsitePhotoItem(
                    url=full,
                    type=classified_type,
                    alt=alt or f"Extracted {classified_type.title()}",
                    selected=(len(photos) < 6)
                ))

        # OpenGraph image
        m_og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_og_img:
            add_photo(m_og_img.group(1), "hero", "Hero Banner")

        # <img> tags
        img_srcs = re.findall(r'<img[^>]+src=["\'](.*?)["\']', html, re.IGNORECASE)
        for src in img_srcs:
            add_photo(src, "product", "Product Image")

        # Clean text
        clean_html = re.sub(r"<(script|style|noscript|iframe|svg)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r"<[^>]+>", " ", clean_html)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()[:4000]

        # OpenGraph Logo / Site Logo
        m_logo = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:)?logo["\'][^>]+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_logo:
            logo_candidate = urljoin(base_url, m_logo.group(1).strip())
        elif not logo_candidate and favicon_url:
            logo_candidate = favicon_url

        # Phone extraction
        extracted_phone = None
        m_tel = re.search(r'href=["\']tel:(.*?)["\']', html, re.IGNORECASE)
        if m_tel:
            extracted_phone = m_tel.group(1).strip()
        if not extracted_phone:
            m_p = re.search(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,6}", clean_text)
            if m_p:
                p_cand = m_p.group(0).strip()
                if sum(c.isdigit() for c in p_cand) >= 7:
                    extracted_phone = p_cand

        parsed_domain = urlparse(base_url).netloc.replace("www.", "")

        return {
            "title": title or parsed_domain.title(),
            "clean_title": title or parsed_domain.title(),
            "description": description or f"Official website of {parsed_domain.title()}",
            "site_name": site_name or parsed_domain.title(),
            "domain": parsed_domain,
            "top_css_colors": top_css_colors,
            "photos": photos,
            "logo_candidate": logo_candidate,
            "hero_candidate": hero_candidate,
            "body_text": clean_text,
            "ld_name": None,
            "ld_city": None,
            "ld_tagline": None,
            "ld_products": [],
            "phone": extracted_phone,
            "phone_number": extracted_phone
        }

    @classmethod
    async def _execute_ai_analysis(cls, extracted: Dict[str, Any], url: str) -> Dict[str, Any]:
        """
        Uses Google Gemini to synthesize all fields shown in the reference screens:
        - Business Details: Business name, Category, Business types, Sub-category, City, Tagline, Target audience, Differentiators, Products/Services
        - Brand Preferences: Tagline card, 5 Brand colors, 16 Tones, 10 Languages, Target audience summary, Services/products summary
        """
        provider = AIProviderFactory.get_provider(preferred="gemini", tier="fast")

        system_instruction = (
            "You are an elite brand strategist and visual design AI. "
            "Analyze the verified website content, copy, CSS colors, structured data, and images extracted from an authentic business website. "
            "Extract every single field required for onboarding matching the UI/UX specification. "
            "Do NOT invent false statistics or fake claims. If city or location is not found in content, return null. "
            "Strictly output valid JSON matching the specified schema."
        )

        candidate_colors = ", ".join(extracted.get("top_css_colors", [])) or "None detected"
        photos_summary = json.dumps([p.model_dump() for p in extracted.get("photos", [])[:8]])
        existing_city = extracted.get("ld_city") or "null"

        prompt = f"""Analyze this website extraction:
URL: {url}
Domain: {extracted.get('domain')}
Page Title: {extracted.get('title')}
Site Name: {extracted.get('site_name')}
Meta Description: {extracted.get('description')}
Detected Website CSS/Theme Colors: {candidate_colors}
Known City / Location: {existing_city}
Extracted Photos/Images: {photos_summary}
Main Copy Snippets:
{extracted.get('body_text', '')}

Provide a complete brand profile formatted as JSON with the following exact structure:
{{
  "business_details": {{
    "business_name": "Clear, clean brand/company name (e.g. SevenUnique Tech Solutions Pvt. Ltd.)",
    "category": "Main business category (e.g. Tech & Electronics, Fashion & Apparel, Healthcare, Retail)",
    "business_types": ["Product-based" | "Physical Location" | "Service / Digital"],
    "primary_business_type": "Primary selection from business_types",
    "sub_category": "Specific sub-category (e.g. Software Development, Ethnic Wear)",
    "city": {json.dumps(extracted.get('ld_city'))},
    "logo_url": "{extracted.get('logo_candidate') or ''}",
    "tagline": "Authentic tagline or value proposition statement",
    "target_audience": "Who buys from you (e.g. Startups, enterprises, and growing businesses)",
    "differentiators": [
      "Authentic USP / differentiator 1 extracted from site facts",
      "Authentic USP / differentiator 2",
      "Authentic USP / differentiator 3"
    ],
    "products_services": [
      "Product or Service 1",
      "Product or Service 2",
      "Product or Service 3",
      "Product or Service 4"
    ]
  }},
  "brand_preferences": {{
    "tagline": "Quote card tagline / brand statement",
    "brand_colors": ["#HEX1", "#HEX2", "#HEX3", "#HEX4", "#HEX5"],
    "tones": ["Modern", "Professional"],
    "default_language": "English",
    "target_audience_summary": "Summary of target customer base",
    "services_products_summary": ["Product or Service 1", "Product or Service 2"]
  }},
  "logo_url": "{extracted.get('logo_candidate') or ''}",
  "hero_image": "{extracted.get('hero_candidate') or ''}",
  "photos": [
    {{
      "url": "full image url",
      "type": "logo | hero | product | gallery",
      "alt": "descriptive alt label",
      "selected": true
    }}
  ]
}}

Tone choices must be strictly from: {json.dumps(VALID_BRAND_TONES)}.
Language choice must be strictly from: {json.dumps(VALID_CONTENT_LANGUAGES)}."""

        res = await provider.generate_json(prompt=prompt, system_prompt=system_instruction)

        if not isinstance(res, dict) or "business_details" not in res:
            logger.warning("Gemini did not return full structured brand analysis; using heuristic synthesis.")
            return cls._build_heuristic_fallback(extracted, url)

        # Parse & Validate BusinessDetails
        b_det_data = res["business_details"]
        if not b_det_data.get("logo_url") and extracted.get("logo_candidate"):
            b_det_data["logo_url"] = extracted["logo_candidate"]
        if not b_det_data.get("city") and extracted.get("ld_city"):
            b_det_data["city"] = extracted["ld_city"]

        business_details = BusinessDetails(**b_det_data)

        # Parse & Validate BrandPreferences
        b_pref_data = res.get("brand_preferences", {})
        # Ensure 5 brand colors
        raw_colors = b_pref_data.get("brand_colors", [])
        if len(raw_colors) < 5:
            fallback_palette = ["#FFFFFF", "#1E1E1E", "#E65100", "#2C2C2C", "#0A0A0A"]
            raw_colors = raw_colors + [c for c in fallback_palette if c not in raw_colors]
        b_pref_data["brand_colors"] = raw_colors[:5]

        # Ensure valid tones
        raw_tones = b_pref_data.get("tones", [])
        valid_tones = [t for t in raw_tones if t in VALID_BRAND_TONES]
        b_pref_data["tones"] = valid_tones if valid_tones else ["Modern", "Professional"]

        # Ensure valid language
        lang = b_pref_data.get("default_language", "English")
        if lang not in VALID_CONTENT_LANGUAGES:
            lang = "English"
        b_pref_data["default_language"] = lang

        brand_preferences = BrandPreferences(**b_pref_data)

        # Photos: Always prioritize authentic extracted photos from the target website
        photo_items: List[WebsitePhotoItem] = []
        discovered_photos = extracted.get("photos", [])
        if discovered_photos:
            photo_items = [p for p in discovered_photos[:20]]
        else:
            for p in res.get("photos", []):
                if isinstance(p, dict) and p.get("url"):
                    photo_items.append(WebsitePhotoItem(
                        url=p["url"],
                        type=p.get("type", "photo"),
                        alt=p.get("alt"),
                        selected=p.get("selected", True)
                    ))

        # Legacy models
        brand_voice = BrandVoiceResult(
            tone=", ".join(brand_preferences.tones),
            tagline=brand_preferences.tagline,
            description=business_details.tagline or f"Official presence of {business_details.business_name}",
            target_audience=business_details.target_audience,
            keywords=business_details.differentiators[:4]
        )
        colors_res = BrandColorsResult(
            primary=brand_preferences.brand_colors[0],
            secondary=brand_preferences.brand_colors[1],
            accent=brand_preferences.brand_colors[2],
            palette=brand_preferences.brand_colors
        )
        category_res = BrandCategoryResult(
            business_name=business_details.business_name,
            primary_category=business_details.category,
            sub_categories=[business_details.sub_category] if business_details.sub_category else [],
            business_type=business_details.primary_business_type,
            summary=business_details.target_audience
        )

        return {
            "business_details": business_details,
            "brand_preferences": brand_preferences,
            "brand_voice": brand_voice,
            "colors": colors_res,
            "category": category_res,
            "photos": photo_items,
            "logo_url": business_details.logo_url or extracted.get("logo_candidate"),
            "hero_image": res.get("hero_image") or extracted.get("hero_candidate")
        }

    @classmethod
    def _build_heuristic_fallback(cls, extracted: Dict[str, Any], url: str) -> Dict[str, Any]:
        """
        Synthesizes authentic brand results directly from parsed HTML tags, JSON-LD, and CSS
        if external AI generation is unavailable. Does not fabricate missing details.
        """
        domain_name = extracted.get("domain", "").split(".")[0].replace("-", " ").title()
        site_name = extracted.get("ld_name") or extracted.get("site_name") or extracted.get("clean_title") or domain_name or "My Business"
        tagline = extracted.get("ld_tagline") or None

        # Category: use identifiable category from JSON-LD or meta/text, else None
        cat_candidate = extracted.get("ld_category")
        if not cat_candidate:
            meta_blob = f"{extracted.get('title', '')} {extracted.get('description', '')}".lower()
            if any(k in meta_blob for k in ["apparel", "clothing", "fashion", "textile", "wear"]):
                cat_candidate = "Fashion & Apparel"
            elif any(k in meta_blob for k in ["software", "tech solutions", "saas", "digital agency", "cloud", "developer"]):
                cat_candidate = "Technology & IT"
            elif any(k in meta_blob for k in ["food", "restaurant", "cafe", "culinary", "bakery", "dining"]):
                cat_candidate = "Food & Beverage"
            elif any(k in meta_blob for k in ["health", "fitness", "wellness", "medical", "clinic"]):
                cat_candidate = "Health & Wellness"
            elif any(k in meta_blob for k in ["store", "shop", "ecommerce", "retail"]):
                cat_candidate = "Retail & E-commerce"

        # CSS colors: strictly use extracted top css colors, do not fabricate neon random palette
        css_colors = extracted.get("top_css_colors", [])
        palette = css_colors[:5] if css_colors else []

        products = extracted.get("ld_products", [])
        photos = extracted.get("photos", [])[:8]

        business_details = BusinessDetails(
            business_name=site_name,
            category=cat_candidate or "General",
            business_types=["Service / Digital"],
            primary_business_type="Service / Digital",
            sub_category=None,
            city=extracted.get("ld_city"),
            logo_url=extracted.get("logo_candidate"),
            tagline=tagline,
            target_audience=None,
            differentiators=[],
            products_services=products
        )

        brand_preferences = BrandPreferences(
            tagline=tagline,
            brand_colors=palette,
            tones=["Modern", "Professional"],
            default_language="English",
            target_audience_summary=None,
            services_products_summary=products
        )

        brand_voice = BrandVoiceResult(
            tone="Modern & Professional",
            tagline=tagline,
            description=tagline or extracted.get("description"),
            target_audience=None,
            keywords=["Modern", "Professional"]
        )

        colors_res = BrandColorsResult(
            primary=palette[0] if len(palette) > 0 else "#FFFFFF",
            secondary=palette[1] if len(palette) > 1 else "#1E1E1E",
            accent=palette[2] if len(palette) > 2 else "#E65100",
            palette=palette
        )

        category_res = BrandCategoryResult(
            business_name=site_name,
            primary_category=business_details.category,
            sub_categories=[],
            business_type="Service / Digital",
            summary=tagline or extracted.get("description")
        )

        return {
            "business_details": business_details,
            "brand_preferences": brand_preferences,
            "brand_voice": brand_voice,
            "colors": colors_res,
            "category": category_res,
            "photos": photos,
            "logo_url": extracted.get("logo_candidate"),
            "hero_image": extracted.get("hero_candidate")
        }


    @classmethod
    async def _update_job(
        cls,
        db,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        current_step: Optional[str] = None,
        onboarding_step: Optional[str] = None,
        step_statuses_update: Optional[Dict[str, str]] = None,
        results: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        extra_updates: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Updates the job document in MongoDB with timestamp and fine-grained step progression.
        """
        now = datetime.now(timezone.utc)
        updates: Dict[str, Any] = {"updated_at": now}

        if status:
            updates["status"] = status
        if progress is not None:
            updates["progress"] = progress
        if current_step:
            updates["current_step"] = current_step
        if onboarding_step:
            updates["onboarding_step"] = onboarding_step
        if results is not None:
            updates["results"] = results
        if error is not None:
            updates["error"] = error

        if step_statuses_update:
            for step_key, step_val in step_statuses_update.items():
                updates[f"step_statuses.{step_key}"] = step_val

        if extra_updates:
            updates.update(extra_updates)

        await db["website_analysis_jobs"].update_one(
            {"job_id": job_id},
            {"$set": updates}
        )

    @classmethod
    async def _sync_results_to_profile(
        cls,
        db,
        user_id: str,
        results: WebsiteAnalysisResults,
        website_url: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Persists extracted Brand Voice, Colors, Category, and Photos to user's
        'brand_kits' and 'businesses' collections.
        """
        now = datetime.now(timezone.utc)
        b_det = results.business_details
        b_pref = results.brand_preferences
        cat = results.category
        bv = results.brand_voice
        col = results.colors

        # 1. Update business collection
        bus_updates: Dict[str, Any] = {
            "owner_id": str(user_id),
            "ownerId": str(user_id),
            "website": website_url,
            "online_presence": "website",
            "updated_at": now
        }

        if b_det:
            bus_updates["name"] = b_det.business_name
            bus_updates["business_name"] = b_det.business_name
            bus_updates["category"] = b_det.category
            bus_updates["business_category"] = b_det.category
            bus_updates["sub_category"] = b_det.sub_category
            bus_updates["city"] = b_det.city
            bus_updates["tagline"] = b_det.tagline
            bus_updates["target_customer"] = b_det.target_audience
            bus_updates["business_types"] = b_det.business_types
            bus_updates["primary_business_type"] = b_det.primary_business_type
            bus_updates["differentiators"] = b_det.differentiators
            bus_updates["products_services"] = b_det.products_services
            bus_updates["logo_url"] = b_det.logo_url
        elif cat:
            bus_updates["name"] = cat.business_name
            bus_updates["business_name"] = cat.business_name
            bus_updates["category"] = cat.primary_category
            bus_updates["business_category"] = cat.primary_category
            bus_updates["business_type"] = cat.business_type or "website"

        if b_pref:
            bus_updates["brand_colors"] = b_pref.brand_colors[:5]
            bus_updates["tones"] = b_pref.tones
            bus_updates["preferred_language"] = b_pref.default_language

        bus_updates["owner_id"] = str(user_id)
        bus_updates["ownerId"] = str(user_id)
        bus_updates["user_id"] = str(user_id)
        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {
                "$set": bus_updates,
                "$setOnInsert": {
                    "name": bus_updates.get("business_name") or "My Business",
                    "business_name": bus_updates.get("business_name") or "My Business",
                    "location": "India",
                    "created_at": now
                }
            },
            upsert=True
        )

        # 2. Update brand_kits collection
        brand_kit_updates: Dict[str, Any] = {
            "business_id": str(user_id),
            "owner_id": str(user_id),
            "online_presence": "website",
            "brand_kit_status": "in_progress",
            "updated_at": now
        }

        if b_det:
            brand_kit_updates["brand_name"] = b_det.business_name
            brand_kit_updates["business_name"] = b_det.business_name
            brand_kit_updates["business_category"] = b_det.category
            brand_kit_updates["sub_category"] = b_det.sub_category
            brand_kit_updates["city"] = b_det.city
            brand_kit_updates["tagline"] = b_det.tagline
            brand_kit_updates["target_audience"] = b_det.target_audience
            brand_kit_updates["business_types"] = b_det.business_types
            brand_kit_updates["primary_business_type"] = b_det.primary_business_type
            brand_kit_updates["differentiators"] = b_det.differentiators
            brand_kit_updates["products_services"] = b_det.products_services
            brand_kit_updates["logo_url"] = b_det.logo_url
        elif cat:
            brand_kit_updates["brand_name"] = cat.business_name
            brand_kit_updates["business_name"] = cat.business_name
            brand_kit_updates["business_category"] = cat.primary_category

        if b_pref:
            brand_kit_updates["palette"] = b_pref.brand_colors[:5]
            brand_kit_updates["brand_colors"] = b_pref.brand_colors[:5]
            brand_kit_updates["primary_color"] = b_pref.brand_colors[0] if b_pref.brand_colors else None
            brand_kit_updates["secondary_color"] = b_pref.brand_colors[1] if len(b_pref.brand_colors) > 1 else None
            brand_kit_updates["accent_color"] = b_pref.brand_colors[2] if len(b_pref.brand_colors) > 2 else None
            brand_kit_updates["tones"] = b_pref.tones
            brand_kit_updates["brand_voice"] = ", ".join(b_pref.tones)
            brand_kit_updates["language"] = b_pref.default_language
            brand_kit_updates["target_audience_summary"] = b_pref.target_audience_summary
            brand_kit_updates["services_products_summary"] = b_pref.services_products_summary

        if results.photos:
            brand_kit_updates["selected_photos"] = [p.url for p in results.photos[:4]]

        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": brand_kit_updates},
            upsert=True
        )

        refreshed_kit = await db["brand_kits"].find_one({"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]}) or {}
        refreshed_bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}

        refreshed_kit.pop("_id", None)
        refreshed_bus.pop("_id", None)

        return refreshed_kit, refreshed_bus

    @classmethod
    async def analyze_website_direct(
        cls,
        db,
        url: str,
        user_id: Optional[str] = None,
        primary_goal: Optional[str] = None,
        target_audience: Optional[str] = None,
        allow_private_for_tests: bool = False
    ) -> Dict[str, Any]:
        """
        Direct end-to-end synchronous website analysis for dynamic onboarding and CRO audits.
        Fetches website HTML, extracts dynamic photos/colors/metadata, synthesizes brand profile,
        and links with MongoDB collections when user_id is provided.
        """
        normalized_url = normalize_website_url(url)
        is_safe, error_msg = validate_url_safety(normalized_url, allow_private_for_tests=allow_private_for_tests)
        if not is_safe:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg or "Target website URL is unsafe or invalid."
            )

        html_content, final_url, fetch_error = await cls._fetch_website(normalized_url, allow_private_for_tests=allow_private_for_tests)
        if fetch_error or not html_content:
            logger.warning(f"Website fetch error for {normalized_url}: {fetch_error}. Returning partial heuristic results.")
            extracted = {
                "title": "",
                "clean_title": "",
                "description": "",
                "meta_description": "",
                "logo_candidate": None,
                "hero_candidate": None,
                "brand_colors": [],
                "photos": [],
                "raw_text": "",
                "headings": []
            }
            ai_results = cls._build_heuristic_fallback(extracted, final_url or normalized_url)
        else:
            extracted = cls._parse_html_content(html_content, final_url or normalized_url)

            try:
                ai_results = await cls._execute_ai_analysis(extracted, final_url or normalized_url)
            except Exception as e:
                logger.error(f"AI brand analysis failed in analyze_website_direct: {e}", exc_info=True)
                ai_results = cls._build_heuristic_fallback(extracted, final_url or normalized_url)

        business_details = ai_results.get("business_details")
        brand_preferences = ai_results.get("brand_preferences")
        discovered_photos: List[WebsitePhotoItem] = ai_results.get("photos", [])

        # Photo URLs list (for frontend components expecting string[])
        photo_urls = [p.url if hasattr(p, "url") else p["url"] for p in discovered_photos]

        # Results Model
        results_model = WebsiteAnalysisResults(
            brand_voice=ai_results.get("brand_voice"),
            colors=ai_results.get("colors"),
            category=ai_results.get("category"),
            photos=discovered_photos,
            logo_url=ai_results.get("logo_url") or extracted.get("logo_candidate"),
            hero_image=ai_results.get("hero_image") or extracted.get("hero_candidate"),
            website_title=extracted.get("title"),
            meta_description=extracted.get("description"),
            business_details=business_details,
            brand_preferences=brand_preferences
        )

        # If user_id provided, persist job and profile
        job_id = None
        if user_id:
            import uuid
            now = datetime.now(timezone.utc)
            job_id = f"job_{uuid.uuid4().hex[:16]}"
            job_doc = {
                "job_id": job_id,
                "user_id": str(user_id),
                "onboarding_type": "website",
                "url": normalized_url,
                "status": "completed",
                "progress": 100,
                "current_step": "completed",
                "onboarding_step": "business_details",
                "step_statuses": {
                    "fetching": "completed",
                    "brand_voice": "completed",
                    "colors": "completed",
                    "category": "completed",
                    "photos": "completed"
                },
                "results": results_model.model_dump(),
                "selected_photo_urls": photo_urls[:4],
                "error": None,
                "created_at": now,
                "updated_at": now
            }
            await db["website_analysis_jobs"].insert_one(job_doc)
            try:
                await cls._sync_results_to_profile(db, user_id, results_model, final_url or normalized_url)
            except Exception as e:
                logger.warning(f"Could not auto-sync analysis to profile in direct mode: {e}")

        b_name = (business_details.business_name if business_details else None) or extracted.get("ld_name") or extracted.get("site_name") or extracted.get("clean_title") or extracted.get("title") or "My Business"
        b_cat = (business_details.category if (business_details and business_details.category not in ("General Business", "General")) else None) or extracted.get("ld_category") or None
        b_tag = (business_details.tagline if business_details else None) or extracted.get("ld_tagline") or None
        palette = (brand_preferences.brand_colors if brand_preferences and brand_preferences.brand_colors else None) or extracted.get("top_css_colors") or []

        primary_col = palette[0] if len(palette) > 0 else None
        secondary_col = palette[1] if len(palette) > 1 else None
        accent_col = palette[2] if len(palette) > 2 else None
        tones = brand_preferences.tones if brand_preferences else []
        logo_url = (business_details.logo_url if business_details else None) or extracted.get("logo_candidate") or None
        phone_val = (business_details.phone if hasattr(business_details, "phone") else None) or extracted.get("phone") or extracted.get("phone_number")

        return {
            "job_id": job_id,
            "status": "completed",
            # Business & Brand Name
            "business_name": b_name,
            "brand_name": b_name,
            # Category
            "category": b_cat,
            "business_category": b_cat,
            "sub_category": business_details.sub_category if business_details else None,
            "business_types": business_details.business_types if business_details else ["Service / Digital"],
            "primary_business_type": business_details.primary_business_type if business_details else "Service / Digital",
            # Description & Title
            "title": extracted.get("title"),
            "website_title": extracted.get("title"),
            "description": extracted.get("description"),
            "meta_description": extracted.get("description"),
            "business_description": extracted.get("description") or b_tag,
            "brand_description": extracted.get("description") or b_tag,
            # Website URL
            "website": normalized_url,
            "website_url": normalized_url,
            # Contact & Phone
            "phone": phone_val,
            "phone_number": phone_val,
            # Brand Colors
            "primary_color": primary_col,
            "secondary_color": secondary_col,
            "accent_color": accent_col,
            "brand_colors": palette[:5],
            "palette": palette[:5],
            # Voice & Tones
            "tones": tones,
            "tone": ", ".join(tones) if tones else None,
            "brand_voice": ", ".join(tones) if tones else None,
            "language": brand_preferences.default_language if brand_preferences else "English",
            # Tagline, Logo, Location
            "tagline": b_tag,
            "logo_url": logo_url,
            "city": business_details.city if business_details else extracted.get("ld_city"),
            "location": {"city": business_details.city if business_details else extracted.get("ld_city")} if ((business_details and business_details.city) or extracted.get("ld_city")) else None,
            # Differentiators & Products
            "target_audience": business_details.target_audience if business_details else None,
            "differentiators": business_details.differentiators if business_details else [],
            "products_services": business_details.products_services if business_details else [],
            # Photos
            "photos": photo_urls,
            "images": photo_urls,
            "photo_items": [p.model_dump() if hasattr(p, "model_dump") else p for p in discovered_photos],
            "selected_photos": photo_urls[:4],
            "overall_health_score": 85,
            "brand_messaging_clarity": b_tag or "Verified online business presence",
            "conversion_funnel_audit": {
                "strengths": business_details.differentiators[:2] if business_details and business_details.differentiators else ["Clear value proposition", "Direct product showcase"],
                "critical_friction_points": ["Highlight key customer reviews", "Ensure frictionless contact/checkout"],
                "cta_recommendations": ["Use high-contrast primary buttons"]
            },
            "seo_and_content_recommendations": {
                "recommended_keywords": [k for k in [b_name, b_cat] if k],
                "meta_improvements": extracted.get("description", "")
            },
            "actionable_next_steps": [
                "Feature your top products/services in primary navigation.",
                "Reinforce credibility with client badges and testimonials.",
                "Ensure mobile responsive media loading."
            ]
        }

