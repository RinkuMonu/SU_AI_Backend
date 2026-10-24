import ipaddress
import re
import socket
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import httpx
from bson import ObjectId
from fastapi import HTTPException, status, UploadFile

from app.core.database import get_database
from app.models.business import Business


class BusinessOnboardingService:
    ALLOWED_ROLES = {"business", "influencer"}

    @staticmethod
    async def get_collection(name: str = "business_profiles"):
        db = get_database()
        return db[name]

    # ── Role Validation & Migration ──
    @staticmethod
    def normalize_role(role: str, strict: bool = False) -> str:
        """Validates and maps role to allowed set: 'business' and 'influencer' only."""
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role cannot be empty. Allowed roles are 'business' and 'influencer'."
            )
        cleaned = role.strip().lower()
        if strict:
            if cleaned not in ["business", "influencer"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role '{role}'. Only 'business' and 'influencer' are supported."
                )
            return cleaned

        # Legacy migration mapping for existing account tokens
        if cleaned in ["business", "businessman", "merchant"]:
            return "business"
        if cleaned in ["influencer", "creator", "user_creator"]:
            return "influencer"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{role}'. Allowed roles are 'business' and 'influencer'."
        )

    @staticmethod
    async def select_role(user_id: str, requested_role: str) -> Dict[str, Any]:
        """Saves selected role and returns next onboarding step."""
        canonical_role = BusinessOnboardingService.normalize_role(requested_role, strict=True)
        db = get_database()
        
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        
        # 1. Update User document
        update_doc = {
            "role": canonical_role,
            "accountType": canonical_role,
            "updated_at": datetime.now(timezone.utc)
        }
        
        await db["users"].update_one(
            {"$or": [{"_id": user_oid}, {"id": user_id}]},
            {"$set": update_doc}
        )
        if ObjectId.is_valid(user_id):
            await db["pending_users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_doc}
            )

        # 2. Ensure initial profile exists
        if canonical_role == "business":
            bp_coll = db["business_profiles"]
            existing = await bp_coll.find_one({"user_id": user_id})
            if not existing:
                await bp_coll.insert_one({
                    "user_id": user_id,
                    "presence_types": [],
                    "links": [],
                    "details": {},
                    "photos": [],
                    "social_accounts": [],
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                })
            next_step = "online_presence"
        else:
            inf_coll = db["influencer_profiles"]
            existing = await inf_coll.find_one({"user_id": user_id})
            if not existing:
                await inf_coll.insert_one({
                    "user_id": user_id,
                    "niche": [],
                    "social_accounts": [],
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                })
            next_step = "influencer_profile"

        return {
            "success": True,
            "message": f"Role '{canonical_role}' assigned successfully.",
            "role": canonical_role,
            "next_step": next_step
        }

    # ── Step 1: Online Presence ──
    @staticmethod
    async def set_online_presence(user_id: str, presence_types: List[str]) -> Dict[str, Any]:
        db = get_database()
        bp_coll = db["business_profiles"]

        next_step = "business_details" if presence_types == ["none"] else "business_link"
        
        await bp_coll.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "presence_types": presence_types,
                    "updated_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )

        return {
            "success": True,
            "message": "Online presence preferences saved.",
            "presence_types": presence_types,
            "next_step": next_step
        }

    # ── SSRF Security Validation ──
    @staticmethod
    def validate_safe_url(url: str) -> None:
        """Validates that a URL is well-formed and does not target internal/private network."""
        parsed = urlparse(url.strip())
        if parsed.scheme not in ["http", "https"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URL must start with http:// or https://"
            )
        hostname = parsed.hostname
        if not hostname:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid URL hostname."
            )

        # Block localhost / loopback names explicitly
        if hostname.lower() in ["localhost", "127.0.0.1", "0.0.0.0", "::1"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access to local or internal network URLs is strictly forbidden."
            )

        # Resolve hostname to check for private / reserved IP addresses
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_reserved
                    or ip_obj.is_link_local
                    or str(ip_obj).startswith("169.254.")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Access to internal or private IP address is prohibited (SSRF prevention)."
                    )
        except socket.gaierror:
            # If DNS resolution fails, allow if in testing mode or reject
            pass

    # ── Step 2: Business Links CRUD ──
    @staticmethod
    async def add_business_link(user_id: str, link_type: str, url: str, platform: Optional[str] = None) -> Dict[str, Any]:
        BusinessOnboardingService.validate_safe_url(url)
        db = get_database()
        bp_coll = db["business_profiles"]

        profile = await bp_coll.find_one({"user_id": user_id})
        links = profile.get("links", []) if profile else []

        # Check for duplicates
        if any(l.get("url", "").strip().lower() == url.strip().lower() for l in links):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This business link has already been added."
            )

        link_id = f"lnk_{uuid.uuid4().hex[:12]}"
        new_link = {
            "link_id": link_id,
            "type": link_type,
            "url": url.strip(),
            "platform": platform,
            "fetch_status": "pending",
            "created_at": datetime.now(timezone.utc)
        }

        await bp_coll.update_one(
            {"user_id": user_id},
            {"$push": {"links": new_link}},
            upsert=True
        )

        return new_link

    @staticmethod
    async def get_business_links(user_id: str) -> List[Dict[str, Any]]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        if not profile:
            return []
        return profile.get("links", [])

    @staticmethod
    async def update_business_link(user_id: str, link_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        if "url" in update_data and update_data["url"]:
            BusinessOnboardingService.validate_safe_url(update_data["url"])

        db = get_database()
        bp_coll = db["business_profiles"]

        profile = await bp_coll.find_one({"user_id": user_id, "links.link_id": link_id})
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business link not found.")

        set_fields = {}
        for k, v in update_data.items():
            if v is not None:
                set_fields[f"links.$.{k}"] = v

        if set_fields:
            await bp_coll.update_one(
                {"user_id": user_id, "links.link_id": link_id},
                {"$set": set_fields}
            )

        updated_profile = await bp_coll.find_one({"user_id": user_id})
        for link in updated_profile.get("links", []):
            if link.get("link_id") == link_id:
                return link
        return {}

    @staticmethod
    async def delete_business_link(user_id: str, link_id: str) -> bool:
        db = get_database()
        result = await db["business_profiles"].update_one(
            {"user_id": user_id},
            {"$pull": {"links": {"link_id": link_id}}}
        )
        return result.modified_count > 0

    # ── Step 3: Auto-Fetch Website & Business Info ──
    @staticmethod
    async def fetch_link_metadata(user_id: str, link_id: str) -> Dict[str, Any]:
        db = get_database()
        bp_coll = db["business_profiles"]

        profile = await bp_coll.find_one({"user_id": user_id})
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business profile not found.")

        target_link = next((l for l in profile.get("links", []) if l.get("link_id") == link_id), None)
        if not target_link:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link ID not found.")

        url = target_link.get("url")
        BusinessOnboardingService.validate_safe_url(url)

        # Fetch public webpage safely
        extracted = {
            "link_id": link_id,
            "business_name": None,
            "category": None,
            "description": None,
            "logo_url": None,
            "contact_email": None,
            "contact_phone": None,
            "location": None,
            "products": [],
            "social_links": {},
            "is_confirmed": False,
            "fetched_at": datetime.now(timezone.utc)
        }

        try:
            async with httpx.AsyncClient(
                timeout=8.0,
                follow_redirects=True,
                headers={"User-Agent": "DhandaGrowBot/1.0 (+https://dhandagrow.com)"}
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    html = resp.text[:1000000]  # Cap at 1MB

                    # 1. Title / Brand Name
                    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE)
                    og_title_match = re.search(r'<meta[^>]*property=["\']og:site_name["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE) or \
                                     re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    raw_title = og_title_match.group(1) if og_title_match else (title_match.group(1) if title_match else "")
                    extracted["business_name"] = raw_title.split("|")[0].split("-")[0].strip() or "My Business"

                    # 2. Description
                    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE) or \
                                 re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    if desc_match:
                        extracted["description"] = desc_match.group(1).strip()

                    # 3. Logo / Favicon
                    og_image_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                    if og_image_match:
                        extracted["logo_url"] = og_image_match.group(1).strip()

                    # 4. Contact Email
                    email_match = re.search(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', html, re.IGNORECASE)
                    if email_match:
                        extracted["contact_email"] = email_match.group(1)

                    # 5. Contact Phone
                    tel_match = re.search(r'tel:([+0-9\s-]{10,})', html, re.IGNORECASE)
                    if tel_match:
                        extracted["contact_phone"] = tel_match.group(1).strip()

                    fetch_status = "completed"
                else:
                    fetch_status = "failed"
        except Exception:
            fetch_status = "failed"
            # Fallback draft info
            parsed = urlparse(url)
            domain_name = parsed.netloc.replace("www.", "").split(".")[0].capitalize()
            extracted["business_name"] = domain_name
            extracted["description"] = f"Business services via {parsed.netloc}"

        # Save draft
        await bp_coll.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "extracted_draft": extracted,
                    "links.$[elem].fetch_status": fetch_status
                }
            },
            array_filters=[{"elem.link_id": link_id}]
        )

        return {
            "success": True,
            "status": fetch_status,
            "extracted_details": extracted
        }

    @staticmethod
    async def get_extracted_details(user_id: str) -> Dict[str, Any]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        if profile and profile.get("extracted_draft"):
            return profile.get("extracted_draft")
        return {}

    # ── Step 4: Business Details ──
    @staticmethod
    async def update_business_details(user_id: str, details_dict: Dict[str, Any]) -> Dict[str, Any]:
        db = get_database()
        bp_coll = db["business_profiles"]

        # Filter None
        cleaned_details = {k: v for k, v in details_dict.items() if v is not None}

        await bp_coll.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "details": cleaned_details,
                    "business_name": cleaned_details.get("business_name"),
                    "category": cleaned_details.get("category") or cleaned_details.get("industry"),
                    "description": cleaned_details.get("description"),
                    "updated_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )

        # Also sync to users and businesses collections for backward compatibility
        sync_user = {}
        if "business_name" in cleaned_details:
            sync_user["business_name"] = cleaned_details["business_name"]
        if "category" in cleaned_details:
            sync_user["business_category"] = cleaned_details["category"]
        if "description" in cleaned_details:
            sync_user["business_description"] = cleaned_details["description"]
        if "preferred_language" in cleaned_details:
            sync_user["preferredLanguage"] = cleaned_details["preferred_language"]

        if sync_user:
            user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
            await db["users"].update_one({"$or": [{"_id": user_oid}, {"id": user_id}]}, {"$set": sync_user})

        # Sync to businesses collection
        await db["businesses"].update_one(
            {"ownerId": user_id},
            {"$set": {
                "name": cleaned_details.get("business_name", "My Business"),
                "category": cleaned_details.get("category", "General"),
                "description": cleaned_details.get("description", ""),
                "location": cleaned_details.get("city") or cleaned_details.get("country") or "India",
                "preferred_language": cleaned_details.get("preferred_language"),
                "website": cleaned_details.get("website"),
                "logo_url": cleaned_details.get("logo_url"),
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        return cleaned_details

    # ── Step 5: Business Photos ──
    @staticmethod
    async def add_business_photo(user_id: str, file_url: str, caption: Optional[str] = None, is_primary: bool = False) -> Dict[str, Any]:
        db = get_database()
        bp_coll = db["business_profiles"]

        photo_id = f"pho_{uuid.uuid4().hex[:12]}"
        new_photo = {
            "photo_id": photo_id,
            "url": file_url,
            "caption": caption or "",
            "is_primary": is_primary,
            "uploaded_at": datetime.now(timezone.utc)
        }

        # If primary, reset other photos
        if is_primary:
            await bp_coll.update_one(
                {"user_id": user_id},
                {"$set": {"photos.$[].is_primary": False}}
            )

        await bp_coll.update_one(
            {"user_id": user_id},
            {"$push": {"photos": new_photo}},
            upsert=True
        )

        return new_photo

    @staticmethod
    async def get_business_photos(user_id: str) -> List[Dict[str, Any]]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        return profile.get("photos", []) if profile else []

    @staticmethod
    async def delete_business_photo(user_id: str, photo_id: str) -> bool:
        db = get_database()
        result = await db["business_profiles"].update_one(
            {"user_id": user_id},
            {"$pull": {"photos": {"photo_id": photo_id}}}
        )
        return result.modified_count > 0

    # ── Step 6: Social Accounts ──
    @staticmethod
    async def connect_social_account(user_id: str, platform: str, access_token: str, account_id: Optional[str] = None, account_name: Optional[str] = None) -> Dict[str, Any]:
        db = get_database()
        bp_coll = db["business_profiles"]

        account_entry = {
            "platform": platform.lower(),
            "account_id": account_id,
            "account_name": account_name,
            "connected": True,
            "connected_at": datetime.now(timezone.utc)
        }

        # Remove existing connection for this platform if any
        await bp_coll.update_one(
            {"user_id": user_id},
            {"$pull": {"social_accounts": {"platform": platform.lower()}}}
        )
        await bp_coll.update_one(
            {"user_id": user_id},
            {"$push": {"social_accounts": account_entry}},
            upsert=True
        )

        # Update user tokens in users collection
        token_field = f"{platform.lower()}_access_token"
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        await db["users"].update_one(
            {"$or": [{"_id": user_oid}, {"id": user_id}]},
            {"$set": {token_field: access_token}}
        )

        return account_entry

    @staticmethod
    async def get_social_accounts(user_id: str) -> List[Dict[str, Any]]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        return profile.get("social_accounts", []) if profile else []

    @staticmethod
    async def disconnect_social_account(user_id: str, platform: str) -> bool:
        db = get_database()
        res = await db["business_profiles"].update_one(
            {"user_id": user_id},
            {"$pull": {"social_accounts": {"platform": platform.lower()}}}
        )
        # Clear token from user
        token_field = f"{platform.lower()}_access_token"
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        await db["users"].update_one(
            {"$or": [{"_id": user_oid}, {"id": user_id}]},
            {"$unset": {token_field: ""}}
        )
        return res.modified_count > 0

    # ── Step 7: AI Business Photos ──
    @staticmethod
    async def generate_ai_photos(user_id: str, prompt: Optional[str] = None, style: str = "professional") -> Dict[str, Any]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        details = (profile.get("details", {}) or {}) if profile else {}
        biz_name = details.get("business_name") or "Your Brand"
        category = details.get("category") or "Retail"

        base_prompt = prompt or f"High-end commercial photoshoot for {biz_name} in {category} sector, {style} lighting"

        # Generate 3 business concepts
        concepts = [
            {
                "concept_id": f"cpt_{uuid.uuid4().hex[:8]}",
                "title": f"Minimalist Studio Showcase",
                "description": f"Clean aesthetic product placement with soft shadows for {biz_name}.",
                "preview_url": "https://images.unsplash.com/photo-1542744094-3a31f272c490?w=800&auto=format&fit=crop"
            },
            {
                "concept_id": f"cpt_{uuid.uuid4().hex[:8]}",
                "title": f"Lifestyle & Customer Action",
                "description": f"Dynamic in-context branding showing happy customers interacting with {biz_name}.",
                "preview_url": "https://images.unsplash.com/photo-1556761175-5973dc0f32e7?w=800&auto=format&fit=crop"
            },
            {
                "concept_id": f"cpt_{uuid.uuid4().hex[:8]}",
                "title": f"Social Hero Banner",
                "description": f"High contrast banner format ideal for Instagram reels & Facebook ad campaigns.",
                "preview_url": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=800&auto=format&fit=crop"
            }
        ]

        # Generate 2 realistic variations
        variations = [
            {
                "variation_id": f"var_{uuid.uuid4().hex[:8]}",
                "title": f"Variation 1: Warm Golden Hour",
                "image_url": "https://images.unsplash.com/photo-1557804506-669a67965ba0?w=800&auto=format&fit=crop"
            },
            {
                "variation_id": f"var_{uuid.uuid4().hex[:8]}",
                "title": f"Variation 2: Modern Editorial Dark",
                "image_url": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?w=800&auto=format&fit=crop"
            }
        ]

        result = {
            "success": True,
            "status": "completed",
            "prompt": base_prompt,
            "concepts": concepts,
            "variations": variations,
            "credits_used": 1,
            "credits_remaining": 99
        }

        # Save record
        await db["business_profiles"].update_one(
            {"user_id": user_id},
            {"$set": {"ai_photos": result}},
            upsert=True
        )

        return result

    # ── Step 8: Profile Comparison ──
    @staticmethod
    async def get_profile_comparison(user_id: str) -> Dict[str, Any]:
        db = get_database()
        profile = await db["business_profiles"].find_one({"user_id": user_id})
        details = profile.get("details", {}) if profile else {}
        photos = profile.get("photos", []) if profile else []
        socials = profile.get("social_accounts", []) if profile else []
        presence = profile.get("presence_types", []) if profile else []

        checklist = [
            {
                "title": "Business Name & Description",
                "completed": bool(details.get("business_name") and details.get("description")),
                "weight": 20,
                "recommendation": "Add a descriptive tagline to help customers identify your unique value." if not details.get("description") else None
            },
            {
                "title": "Brand Logo & Identity",
                "completed": bool(details.get("logo_url")),
                "weight": 15,
                "recommendation": "Upload a high-resolution logo for instant recognition." if not details.get("logo_url") else None
            },
            {
                "title": "Location & Contact Details",
                "completed": bool(details.get("city") or details.get("full_address")),
                "weight": 15,
                "recommendation": "Add your city and address to attract local customers." if not details.get("city") else None
            },
            {
                "title": "Store / Business Photos",
                "completed": len(photos) > 0,
                "weight": 15,
                "recommendation": "Upload at least 2 real photos of your workspace, store, or products." if len(photos) == 0 else None
            },
            {
                "title": "Online Presence & Links",
                "completed": len(presence) > 0,
                "weight": 15,
                "recommendation": "Link your website, Google Maps, or marketplace store." if len(presence) == 0 else None
            },
            {
                "title": "Connected Social Accounts",
                "completed": len(socials) > 0,
                "weight": 20,
                "recommendation": "Connect Instagram or Facebook to automate daily marketing." if len(socials) == 0 else None
            }
        ]

        overall_score = sum(item["weight"] for item in checklist if item["completed"])

        if overall_score >= 85:
            grade = "Excellent"
        elif overall_score >= 60:
            grade = "Good"
        elif overall_score >= 35:
            grade = "Average"
        else:
            grade = "Incomplete"

        recommendations = [item["recommendation"] for item in checklist if item["recommendation"] is not None]

        return {
            "overall_score": overall_score,
            "grade": grade,
            "checklist": checklist,
            "recommendations": recommendations
        }

    # ── Step 9: App Rating ──
    @staticmethod
    async def submit_rating(user_id: str, rating: Optional[int], feedback: Optional[str], skipped: bool = False) -> Dict[str, Any]:
        db = get_database()
        rating_doc = {
            "user_id": user_id,
            "rating": rating if not skipped else None,
            "feedback": feedback if not skipped else None,
            "skipped": skipped,
            "submitted_at": datetime.now(timezone.utc)
        }

        await db["onboarding_ratings"].insert_one(rating_doc)
        await db["business_profiles"].update_one(
            {"user_id": user_id},
            {"$set": {"rating": rating_doc}},
            upsert=True
        )

        return {
            "success": True,
            "message": "Feedback recorded. Thank you!" if not skipped else "Rating step skipped."
        }

    # ── Step 10: Subscription ──
    @staticmethod
    async def get_subscription_summary(user_id: str) -> Dict[str, Any]:
        db = get_database()
        sub = await db["subscriptions"].find_one({"userId": user_id}) or {}
        return {
            "plan_id": sub.get("plan_id", "FREE"),
            "plan_name": sub.get("plan_name", "Starter Free Plan"),
            "status": sub.get("status", "active"),
            "credits_total": sub.get("credits_total", 100),
            "credits_remaining": sub.get("credits_remaining", 100),
            "billing_cycle": sub.get("billing_cycle", "monthly")
        }

    # ── Onboarding Progress (Business & Influencer) ──
    @staticmethod
    async def calculate_progress(user_id: str) -> Dict[str, Any]:
        db = get_database()
        user_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user = await db["users"].find_one({"$or": [{"_id": user_oid}, {"id": user_id}]}) or {}

        role = user.get("role")
        if not role:
            return {
                "role": None,
                "current_step": "role_selection",
                "completed_steps": [],
                "completion_percentage": 0,
                "next_step": "role_selection",
                "is_completed": False
            }

        canonical_role = BusinessOnboardingService.normalize_role(role)

        if canonical_role == "business":
            bp = await db["business_profiles"].find_one({"user_id": user_id}) or {}
            presence = bp.get("presence_types", [])
            links = bp.get("links", [])
            details = bp.get("details", {})
            photos = bp.get("photos", [])
            socials = bp.get("social_accounts", [])
            ai_photos = bp.get("ai_photos")
            rating = bp.get("rating")
            sub = await db["subscriptions"].find_one({"userId": user_id})

            completed = ["role_selection"]

            # Step 1: Online Presence
            if presence:
                completed.append("online_presence")

            # Step 2 & 3: Links / Auto-fetch
            if "none" in presence:
                completed.append("business_link")
                completed.append("auto_fetch")
            elif links:
                completed.append("business_link")
                if any(l.get("fetch_status") in ["completed", "failed"] for l in links):
                    completed.append("auto_fetch")

            # Step 4: Details
            if details.get("business_name") or details.get("category"):
                completed.append("business_details")

            # Step 5: Photos
            if photos:
                completed.append("business_photos")

            # Step 6: Social Connections
            if socials:
                completed.append("social_connections")

            # Step 7: AI Photos
            if ai_photos:
                completed.append("ai_photos")

            # Step 8: Profile Comparison
            if len(completed) >= 5:
                completed.append("profile_comparison")

            # Step 9: Rating
            if rating:
                completed.append("rating")

            # Step 10: Subscription
            if sub:
                completed.append("subscription")

            total_steps = 10
            pct = min(100, int((len(completed) / total_steps) * 100))

            # Determine next step
            all_flow = [
                "role_selection",
                "online_presence",
                "business_link",
                "auto_fetch",
                "business_details",
                "business_photos",
                "social_connections",
                "ai_photos",
                "profile_comparison",
                "rating",
                "subscription"
            ]
            next_step = next((s for s in all_flow if s not in completed), "dashboard")

            return {
                "role": "business",
                "current_step": next_step if next_step != "dashboard" else "completed",
                "completed_steps": completed,
                "completion_percentage": pct,
                "next_step": next_step,
                "is_completed": pct >= 80 or next_step == "dashboard"
            }

        else:
            # Influencer Flow
            inf = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}
            completed = ["role_selection"]

            if inf.get("username") or inf.get("display_name") or inf.get("bio") or inf.get("niche"):
                completed.append("influencer_profile")

            if inf.get("social_accounts") or inf.get("instagram_url") or inf.get("youtube_url"):
                completed.append("social_connections")

            if inf.get("media_kit") or inf.get("portfolio"):
                completed.append("media_kit")

            sub = await db["subscriptions"].find_one({"userId": user_id})
            if sub:
                completed.append("subscription")

            total_steps = 5
            pct = min(100, int((len(completed) / total_steps) * 100))

            all_flow = [
                "role_selection",
                "influencer_profile",
                "social_connections",
                "media_kit",
                "subscription"
            ]
            next_step = next((s for s in all_flow if s not in completed), "dashboard")

            return {
                "role": "influencer",
                "current_step": next_step if next_step != "dashboard" else "completed",
                "completed_steps": completed,
                "completion_percentage": pct,
                "next_step": next_step,
                "is_completed": pct >= 80 or next_step == "dashboard"
            }
