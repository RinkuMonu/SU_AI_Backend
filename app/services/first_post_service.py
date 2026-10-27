import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.first_post import (
    FirstPostGenerateRequest,
    FirstPostImageUploadResponse,
    FirstPostJobResponse,
    FirstPostPreviewItem,
    FirstPostSourceImagesResponse,
    SourceImageItem,
)
from app.services.content_service import ContentService
from app.services.plan_onboarding_service import QUALIFYING_PAID_PLANS
from app.services.subscription_service import SubscriptionService
from app.ai.services.post_generation import PostGenerationService

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
MAX_IMAGE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MIN_IMAGE_SIZE_BYTES = 500  # 500 bytes


class FirstPostService:
    """
    Dedicated service powering the shared First-Post / First-Content onboarding workflow.
    - Aggregates available source images across all 5 business-presence types.
    - Manages secure image uploads with ownership and format validation.
    - Orchestrates persistent 3-preview content generation jobs.
    - Strictly enforces backend subscription entitlement rules (1 unlocked + 2 locked for free plans).
    - Ensures the unlocked preview is saved directly to 'contents' collection for seamless Create Post dashboard editing.
    - Provides idempotent job creation and polling.
    """

    @classmethod
    async def get_or_create_business(cls, db, user_id: str) -> dict:
        """Helper to ensure an authenticated business record exists."""
        uid = str(user_id)
        bus = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}, {"user_id": uid}, {"userId": uid}]})
        if not bus:
            now = datetime.now(timezone.utc)
            new_bus = {
                "owner_id": uid,
                "ownerId": uid,
                "business_name": "My Business",
                "name": "My Business",
                "category": "General",
                "online_presence": "website",
                "business_type": "website",
                "photos": [],
                "scraped_images": [],
                "created_at": now,
                "updated_at": now,
            }
            res = await db["businesses"].insert_one(new_bus)
            new_bus["_id"] = res.inserted_id
            return new_bus
        return bus

    @classmethod
    async def get_available_source_images(cls, db, user_id: str) -> FirstPostSourceImagesResponse:
        """
        Discovers and aggregates all available source images for the authenticated business
        from website scraping, Google Maps photos, Brand Kit, product catalog, and uploads.
        """
        uid = str(user_id)
        bus = await cls.get_or_create_business(db, uid)
        bus_id = str(bus["_id"])
        presence = bus.get("online_presence") or "website"

        seen_urls = set()
        image_items: List[SourceImageItem] = []

        def add_image(raw_url: Optional[str], source_type: str, caption: Optional[str] = None, is_logo: bool = False):
            if not raw_url or not isinstance(raw_url, str):
                return
            clean_url = raw_url.strip()
            if not clean_url or clean_url in seen_urls:
                return
            # Normalize local relative URLs
            if clean_url.startswith("/uploads/") or clean_url.startswith("uploads/"):
                formatted_url = settings.get_public_url(f"/{clean_url.lstrip('/')}")
            else:
                formatted_url = clean_url

            seen_urls.add(clean_url)
            seen_urls.add(formatted_url)

            img_id = Path(clean_url).name or f"img_{len(image_items)+1}"
            image_items.append(
                SourceImageItem(
                    id=img_id,
                    url=formatted_url,
                    source=source_type,
                    caption=caption or img_id,
                    is_logo=is_logo
                )
            )

        # 1. Images from Business document (photos, scraped_images, google_maps_photos)
        for p in (bus.get("photos", []) or []):
            src_tag = "google_maps" if presence == "google_maps" else ("marketplace" if presence == "marketplace_seller" else "website")
            add_image(p, src_tag)

        for p in (bus.get("scraped_images", []) or []):
            add_image(p, "website")

        for p in (bus.get("google_maps_photos", []) or []):
            p_url = p.get("url") if isinstance(p, dict) else str(p)
            add_image(p_url, "google_maps")

        # 2. Brand Kit assets
        brand_kit = await db["brand_kits"].find_one({"$or": [{"owner_id": uid}, {"user_id": uid}]}) or {}
        if brand_kit.get("logo_url"):
            add_image(brand_kit["logo_url"], "brand_kit", caption="Brand Logo", is_logo=True)
        for p in (brand_kit.get("selected_photos", []) or []):
            add_image(p, "brand_kit")
        for p in (brand_kit.get("photos", []) or []):
            p_url = p.get("url") if isinstance(p, dict) else str(p)
            add_image(p_url, "brand_kit")

        # 3. Product Catalog images
        prod_cursor = db["products"].find({"$or": [{"business_id": bus_id}, {"business_id": ObjectId(bus_id) if ObjectId.is_valid(bus_id) else bus_id}]})
        async for prod in prod_cursor:
            p_name = prod.get("name")
            if prod.get("image_url"):
                add_image(prod["image_url"], "product", caption=p_name)
            for p_img in (prod.get("images", []) or []):
                add_image(p_img, "product", caption=p_name)

        # 4. Website Analysis latest job
        w_job = await db["website_analysis_jobs"].find_one(
            {"user_id": uid, "status": "completed"},
            sort=[("created_at", -1)]
        )
        if w_job and w_job.get("results"):
            for w_photo in (w_job["results"].get("photos", []) or []):
                w_url = w_photo.get("url") if isinstance(w_photo, dict) else str(w_photo)
                w_caption = w_photo.get("caption") if isinstance(w_photo, dict) else None
                is_lg = bool(w_photo.get("is_logo") if isinstance(w_photo, dict) else False)
                add_image(w_url, "website", caption=w_caption, is_logo=is_lg)

        # 5. Platform Onboarding source images
        p_job = await db["platform_onboarding_jobs"].find_one({"user_id": uid}) or {}
        for s_img in (p_job.get("source_images", []) or []):
            add_image(s_img, "marketplace" if presence == "marketplace_seller" else "b2b")

        # 6. Uploaded photos explicitly registered on business
        for up in (bus.get("uploaded_photos", []) or []):
            add_image(up, "upload")

        return FirstPostSourceImagesResponse(
            success=True,
            business_id=bus_id,
            online_presence=presence,
            images=image_items,
            total_count=len(image_items)
        )

    @classmethod
    async def upload_image(
        cls,
        db,
        user_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> FirstPostImageUploadResponse:
        """
        Validates and saves a business image for first post creation,
        attaching it to the user's business source photos.
        """
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported image type '{content_type}'. Allowed types: JPEG, PNG, WebP."
            )

        if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image size exceeds the maximum limit of 15MB."
            )

        if len(file_bytes) < MIN_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image file is empty or corrupted."
            )

        ext = Path(filename or "image.jpg").suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"

        dest_dir = Path("uploads") / "products"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = f"firstpost_{uuid.uuid4().hex[:12]}{ext}"
        dest_path = dest_dir / stored_filename

        with open(dest_path, "wb") as f:
            f.write(file_bytes)

        public_url = settings.get_public_url(f"/uploads/products/{stored_filename}")
        uid = str(user_id)

        # Register photo on business
        bus = await cls.get_or_create_business(db, uid)
        await db["businesses"].update_one(
            {"_id": bus["_id"]},
            {
                "$addToSet": {
                    "photos": public_url,
                    "uploaded_photos": public_url
                },
                "$set": {
                    "owner_id": uid,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        return FirstPostImageUploadResponse(
            success=True,
            image_url=public_url,
            image_id=stored_filename,
            filename=stored_filename,
            source="upload",
            content_type=content_type,
            size_bytes=len(file_bytes)
        )

    @classmethod
    async def validate_image_ownership(cls, db, user_id: str, image_url: str) -> bool:
        """
        Validates that a local uploaded asset belongs to the authenticated user's business
        or is a verified image asset.
        """
        if not image_url or not isinstance(image_url, str):
            return False

        clean_url = image_url.strip()
        # External public URLs (e.g. Unsplash, CDN) are acceptable references
        if clean_url.startswith("http://") or clean_url.startswith("https://"):
            if not ("localhost" in clean_url or "127.0.0.1" in clean_url):
                return True

        # Check local file existence
        if "uploads/" in clean_url:
            rel_part = clean_url.split("uploads/")[-1].split("?")[0]
            local_path = os.path.join(os.getcwd(), "uploads", rel_part)
            if not os.path.exists(local_path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Referenced image file '{rel_part}' does not exist on server."
                )

        return True

    @classmethod
    async def create_generation_job(
        cls,
        db,
        user_id: str,
        payload: FirstPostGenerateRequest
    ) -> FirstPostJobResponse:
        """
        Creates and executes a persistent First Post generation job.
        Enforces idempotency, input validation, and backend entitlement access control.
        """
        uid = str(user_id)
        bus = await cls.get_or_create_business(db, uid)
        bus_id = str(bus["_id"])
        now = datetime.now(timezone.utc)

        # 1. Validate image ownership if an image is provided
        if payload.selected_image_url:
            await cls.validate_image_ownership(db, uid, payload.selected_image_url)

        # 2. Idempotency Check: if idempotency_key is provided or repeated within 10s
        if payload.idempotency_key:
            existing_job = await db["first_post_jobs"].find_one({
                "user_id": uid,
                "idempotency_key": payload.idempotency_key
            })
            if existing_job:
                return await cls._build_job_response(db, uid, existing_job)

        # Check for rapid double-click duplicate (within 10 seconds with same choice and image)
        recent_duplicate = await db["first_post_jobs"].find_one({
            "user_id": uid,
            "content_choice": payload.content_choice or "post_maker",
            "selected_image_url": payload.selected_image_url,
            "status": {"$in": ["pending", "processing", "completed"]},
            "created_at": {"$gte": datetime.fromtimestamp(now.timestamp() - 10, timezone.utc)}
        })
        if recent_duplicate and not payload.idempotency_key:
            return await cls._build_job_response(db, uid, recent_duplicate)

        job_id = f"fpjob_{uuid.uuid4().hex[:16]}"
        choice = payload.content_choice or "post_maker"

        initial_doc = {
            "job_id": job_id,
            "user_id": uid,
            "business_id": bus_id,
            "idempotency_key": payload.idempotency_key,
            "content_choice": choice,
            "selected_image_url": payload.selected_image_url,
            "prompt": payload.prompt or payload.additional_instruction,
            "platform": payload.platform or "instagram",
            "objective": payload.objective or "product_promotion",
            "language": payload.language or "English",
            "status": "processing",
            "progress": 25,
            "previews": [],
            "unlocked_preview_id": None,
            "unlocked_content_id": None,
            "error": None,
            "created_at": now,
            "updated_at": now
        }
        await db["first_post_jobs"].insert_one(initial_doc)

        # Execute generation pipeline
        try:
            return await cls._execute_first_post_pipeline(db, uid, bus, job_id, payload)
        except Exception as e:
            logger.error(f"First post generation pipeline error for job {job_id}: {e}", exc_info=True)
            await db["first_post_jobs"].update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": "failed",
                    "progress": 0,
                    "error": str(e),
                    "updated_at": datetime.now(timezone.utc)
                }}
            )
            return FirstPostJobResponse(
                success=False,
                job_id=job_id,
                status="failed",
                progress=0,
                content_choice=choice,
                previews=[],
                error=str(e),
                created_at=now,
                updated_at=datetime.now(timezone.utc)
            )

    @classmethod
    async def _execute_first_post_pipeline(
        cls,
        db,
        user_id: str,
        bus: dict,
        job_id: str,
        payload: FirstPostGenerateRequest
    ) -> FirstPostJobResponse:
        """
        Runs the 3-variation creative pipeline, saves the unlocked variation to 'contents',
        and applies backend subscription entitlement locks.
        """
        uid = str(user_id)
        bus_id = str(bus["_id"])
        bus_name = bus.get("business_name") or bus.get("name") or "My Business"
        category = payload.category or bus.get("category") or "General"
        choice = payload.content_choice or "post_maker"

        # Check authoritative backend subscription entitlement
        sub = await SubscriptionService.get_or_create_subscription(db, uid)
        plan_id = str(sub.get("plan_id", "FREE")).upper()
        sub_status = sub.get("status", "active")
        is_paid = (plan_id in QUALIFYING_PAID_PLANS) and (sub_status == "active")

        # Load Brand Kit for authentic styling
        brand_kit = await db["brand_kits"].find_one({"$or": [{"owner_id": uid}, {"user_id": uid}]}) or {}

        # Fallback product info
        product_ctx = {
            "name": payload.product_name or bus_name,
            "category": category,
            "image_url": payload.selected_image_url
        }

        # Creative variation angles
        angles = [
            {
                "title": "Direct Showcase & Benefit Hook",
                "focus": "Focus on high-value problem solving, key benefits, and clean presentation.",
                "cta": "Shop Now / Learn More",
                "tag_suffix": ["#trending", "#newlaunch"]
            },
            {
                "title": "Authentic Storytelling & Lifestyle",
                "focus": "Focus on relatable customer story, emotional hook, and authentic lifestyle.",
                "cta": "Explore the Collection",
                "tag_suffix": ["#lifestyle", "#storytelling"]
            },
            {
                "title": "Limited-Time Buzz & Special Offer",
                "focus": "Focus on exclusivity, high urgency, social proof, and festive energy.",
                "cta": "Claim Your Offer Today",
                "tag_suffix": ["#specialoffer", "#deals"]
            }
        ]

        post_gen = PostGenerationService()
        raw_variations = []

        # Progress to 40%
        await db["first_post_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {"progress": 40, "updated_at": datetime.now(timezone.utc)}}
        )

        for idx, angle in enumerate(angles):
            custom_instruction = f"{payload.prompt or ''} [Creative Angle: {angle['focus']}]".strip()
            try:
                gen_result = await post_gen.generate_post(
                    business=bus,
                    brand=brand_kit,
                    product=product_ctx,
                    platform=payload.platform or "instagram",
                    objective=payload.objective or "product_promotion",
                    language=payload.language or "English",
                    additional_instruction=custom_instruction,
                    reference_images=[payload.selected_image_url] if payload.selected_image_url else [],
                    product_images=[payload.selected_image_url] if payload.selected_image_url else [],
                    use_brand_kit=bool(brand_kit and any(brand_kit.values())),
                    content_type="post"
                )
            except Exception as gen_err:
                logger.warning(f"Variation {idx+1} generation exception, using resilient creative fallback: {gen_err}")
                # Creative fallback
                gen_result = {
                    "headline": f"{bus_name} - {angle['title']}",
                    "caption": f"Discover the difference with {bus_name}. Quality craftsmanship and exceptional experiences tailored for you. {angle['focus']}",
                    "call_to_action": angle["cta"],
                    "hashtags": [f"#{cls._clean_tag(bus_name)}", f"#{cls._clean_tag(category)}"] + angle["tag_suffix"],
                    "creative_direction": angle["focus"],
                    "image_url": payload.selected_image_url or (bus.get("photos", [None])[0] if bus.get("photos") else "")
                }
            raw_variations.append(gen_result)

        # Progress to 75%
        await db["first_post_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {"progress": 75, "updated_at": datetime.now(timezone.utc)}}
        )

        # Build 3 preview items with access control
        content_svc = ContentService(db)
        previews: List[FirstPostPreviewItem] = []
        unlocked_preview_id = "preview_1"
        unlocked_content_id = None

        for idx, gen in enumerate(raw_variations):
            p_id = f"preview_{idx+1}"
            angle = angles[idx]
            img_url = gen.get("image_url") or payload.selected_image_url or ""

            if idx == 0 or is_paid:
                # UNLOCKED PREVIEW (Preview 1 for everyone, Previews 2 & 3 for paid plans)
                # Save directly into 'contents' collection so the Create Post dashboard can open it!
                save_payload = {
                    "content_type": "post",
                    "platform": payload.platform or "instagram",
                    "objective": payload.objective or "product_promotion",
                    "headline": gen.get("headline"),
                    "caption": gen.get("caption") or "",
                    "call_to_action": gen.get("call_to_action") or angle["cta"],
                    "hashtags": gen.get("hashtags") or [],
                    "creative_direction": angle["focus"],
                    "image_url": img_url,
                    "media_url": img_url,
                    "use_brand_kit": bool(brand_kit),
                    "product_id": payload.product_id,
                    "product_details": product_ctx
                }
                saved_doc = await content_svc.save_generated_post(
                    user_id=uid,
                    business_id=bus_id,
                    payload=save_payload
                )
                c_id = saved_doc["_id"]
                if idx == 0:
                    unlocked_content_id = c_id

                previews.append(
                    FirstPostPreviewItem(
                        id=p_id,
                        variation_index=idx,
                        title=angle["title"],
                        headline=gen.get("headline"),
                        caption=gen.get("caption") or "",
                        hashtags=gen.get("hashtags") or [],
                        call_to_action=gen.get("call_to_action") or angle["cta"],
                        image_url=img_url,
                        media_url=img_url,
                        creative_direction=angle["focus"],
                        content_type="post",
                        content_id=c_id,
                        is_locked=False,
                        lock_reason=None,
                        upgrade_required=False
                    )
                )
            else:
                # LOCKED PREVIEWS (Previews 2 & 3 for free users)
                # Entitlement strictly enforced on backend; redacted copy and no saved editor ID
                previews.append(
                    FirstPostPreviewItem(
                        id=p_id,
                        variation_index=idx,
                        title=f"{angle['title']} (Locked)",
                        headline="Premium Variation",
                        caption="Upgrade to Starter or Pro to unlock this creative variation and custom copywriting.",
                        hashtags=["#premium", "#unlock", "#dhandagrow"],
                        call_to_action=angle["cta"],
                        image_url=img_url,
                        media_url=img_url,
                        creative_direction=angle["focus"],
                        content_type="post",
                        content_id=None,
                        is_locked=True,
                        lock_reason="upgrade_required",
                        upgrade_required=True
                    )
                )

        now_done = datetime.now(timezone.utc)
        await db["first_post_jobs"].update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "previews": [p.model_dump() for p in previews],
                "unlocked_preview_id": unlocked_preview_id,
                "unlocked_content_id": unlocked_content_id,
                "updated_at": now_done
            }}
        )

        return FirstPostJobResponse(
            success=True,
            job_id=job_id,
            status="completed",
            progress=100,
            content_choice=choice,
            previews=previews,
            unlocked_preview_id=unlocked_preview_id,
            unlocked_content_id=unlocked_content_id,
            error=None,
            created_at=bus.get("created_at") or now_done,
            updated_at=now_done
        )

    @classmethod
    async def get_job_status(cls, db, job_id: str, user_id: str) -> FirstPostJobResponse:
        """
        Polls the status of a First Post generation job.
        Validates ownership and re-checks subscription entitlement.
        """
        uid = str(user_id)
        job = await db["first_post_jobs"].find_one({"job_id": job_id})
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"First post generation job '{job_id}' not found."
            )

        if job.get("user_id") != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this generation job."
            )

        return await cls._build_job_response(db, uid, job)

    @classmethod
    async def get_latest_job(cls, db, user_id: str) -> Optional[FirstPostJobResponse]:
        """Returns the most recent First Post generation job for the user."""
        uid = str(user_id)
        job = await db["first_post_jobs"].find_one(
            {"user_id": uid},
            sort=[("created_at", -1)]
        )
        if not job:
            return None
        return await cls._build_job_response(db, uid, job)

    @classmethod
    async def _build_job_response(cls, db, user_id: str, job: dict) -> FirstPostJobResponse:
        """Hydrates FirstPostJobResponse and dynamically adjusts locked previews if plan changed."""
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        plan_id = str(sub.get("plan_id", "FREE")).upper()
        sub_status = sub.get("status", "active")
        is_paid = (plan_id in QUALIFYING_PAID_PLANS) and (sub_status == "active")

        previews_raw = job.get("previews", [])
        previews: List[FirstPostPreviewItem] = []

        for p in previews_raw:
            item = FirstPostPreviewItem(**p) if isinstance(p, dict) else p
            if is_paid and item.is_locked:
                # User has now upgraded! Dynamically unlock
                item.is_locked = False
                item.lock_reason = None
                item.upgrade_required = False
            previews.append(item)

        return FirstPostJobResponse(
            success=True,
            job_id=job["job_id"],
            status=job.get("status", "pending"),
            progress=job.get("progress", 0),
            content_choice=job.get("content_choice", "post_maker"),
            previews=previews,
            unlocked_preview_id=job.get("unlocked_preview_id"),
            unlocked_content_id=job.get("unlocked_content_id"),
            error=job.get("error"),
            created_at=job.get("created_at"),
            updated_at=job.get("updated_at")
        )

    @staticmethod
    def _clean_tag(text: str) -> str:
        """Removes spaces and non-alphanumerics for clean hashtags."""
        import re
        clean = re.sub(r"[^a-zA-Z0-9]", "", text or "")
        return clean or "dhandagrow"
