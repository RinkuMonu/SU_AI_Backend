import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from bson import ObjectId

logger = logging.getLogger(__name__)

class InfluencerService:
    @staticmethod
    async def get_influencer_profile(db, user_id: str) -> Dict[str, Any]:
        """Fetch unified profile of authenticated influencer from users and influencer_profiles collections."""
        # 1. Fetch user record
        user_filter = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"_id": user_id}
        user = await db["users"].find_one(user_filter)
        if not user:
            user = await db["users"].find_one({"id": user_id})
        
        # 2. Fetch or create influencer profile doc
        profile_doc = await db["influencer_profiles"].find_one({"user_id": str(user_id)})
        if not profile_doc and user:
            profile_doc = {
                "user_id": str(user_id),
                "fullName": user.get("fullName") or user.get("name") or "",
                "username": user.get("email", "").split("@")[0],
                "email": user.get("email", ""),
                "phone": user.get("phone") or user.get("contactNumber") or "",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            await db["influencer_profiles"].insert_one(profile_doc)

        profile_doc = profile_doc or {}
        
        # Merge fields
        full_name = profile_doc.get("fullName") or (user.get("fullName") if user else "") or (user.get("name") if user else "Creator")
        email = profile_doc.get("email") or (user.get("email") if user else "")
        username = profile_doc.get("username") or email.split("@")[0] or "creator"
        phone = profile_doc.get("phone") or (user.get("phone") if user else "")
        category = profile_doc.get("category") or profile_doc.get("niche") or "Lifestyle & Fashion"
        bio = profile_doc.get("bio") or ""
        location = profile_doc.get("location") or f"{profile_doc.get('city', '')}, {profile_doc.get('state', '')}".strip(", ") or "India"
        instagram_url = profile_doc.get("instagram_url") or ""
        youtube_url = profile_doc.get("youtube_url") or ""
        follower_count = int(profile_doc.get("follower_count") or 0)
        engagement_rate = float(profile_doc.get("engagement_rate") or 0.0)
        expected_rate = float(profile_doc.get("expectedPricePerPost") or 0.0)
        profile_image = profile_doc.get("profile_image") or (user.get("profileImageUrl") if user else None) or (user.get("image") if user else None)
        
        # Connected platforms calculation
        connected_platforms = []
        if instagram_url:
            connected_platforms.append("Instagram")
        if youtube_url:
            connected_platforms.append("YouTube")
        if profile_doc.get("facebook_url"):
            connected_platforms.append("Facebook")
        if profile_doc.get("linkedin_url"):
            connected_platforms.append("LinkedIn")

        # Completion calculation
        score = 0
        total_items = 7
        if full_name: score += 1
        if username: score += 1
        if bio: score += 1
        if category: score += 1
        if location and location != "India": score += 1
        if follower_count > 0: score += 1
        if connected_platforms: score += 1
        
        completion = int((score / total_items) * 100)

        return {
            "id": str(profile_doc.get("_id", user_id)),
            "user_id": str(user_id),
            "fullName": full_name,
            "username": username if username.startswith("@") else f"@{username}",
            "email": email,
            "phone": phone,
            "bio": bio,
            "category": category,
            "location": location,
            "preferredLanguage": profile_doc.get("preferredLanguage", "English"),
            "instagram_url": instagram_url,
            "youtube_url": youtube_url,
            "follower_count": follower_count,
            "engagement_rate": engagement_rate,
            "expectedPricePerPost": expected_rate,
            "profile_image": profile_image,
            "profile_completion": completion,
            "is_social_connected": len(connected_platforms) > 0,
            "connected_platforms": connected_platforms
        }

    @staticmethod
    async def update_influencer_profile(db, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update or create influencer profile doc and synchronize with user entity."""
        clean_data = {k: v for k, v in data.items() if v is not None}
        clean_data["user_id"] = str(user_id)
        clean_data["updated_at"] = datetime.now(timezone.utc)
        clean_data.pop("_id", None)
        clean_data.pop("id", None)

        await db["influencer_profiles"].update_one(
            {"user_id": str(user_id)},
            {"$set": clean_data},
            upsert=True
        )

        # Sync key fields to users collection
        user_sync = {}
        if "fullName" in clean_data:
            user_sync["fullName"] = clean_data["fullName"]
            user_sync["name"] = clean_data["fullName"]
        if "phone" in clean_data:
            user_sync["phone"] = clean_data["phone"]
            user_sync["contactNumber"] = clean_data["phone"]
        if "profile_image" in clean_data:
            user_sync["profileImageUrl"] = clean_data["profile_image"]

        if user_sync:
            user_filter = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"_id": user_id}
            await db["users"].update_one(user_filter, {"$set": user_sync})

        return await InfluencerService.get_influencer_profile(db, user_id)

    @staticmethod
    async def get_dashboard_summary(db, user_id: str) -> Dict[str, Any]:
        """Aggregate summary statistics for the authenticated influencer dashboard."""
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # 1. Total available opportunities
        # Check active published campaigns and collaboration opportunities
        total_opps = await db["campaigns"].count_documents({"status": {"$ne": "archived"}})
        
        # Count created in last 7 days
        # Support both datetime and ISO string timestamps
        new_opps_count = await db["campaigns"].count_documents({
            "$or": [
                {"createdAt": {"$gte": seven_days_ago}},
                {"created_at": {"$gte": seven_days_ago}},
                {"created_at": {"$gte": seven_days_ago.isoformat()}}
            ]
        })

        # 2. Influencer active and completed applications/collaborations
        applications_cursor = db["campaign_applications"].find({"influencer_id": str(user_id)})
        apps = await applications_cursor.to_list(length=200)

        active_collabs = sum(1 for a in apps if a.get("status") in ["accepted", "active", "in_progress", "submitted"])
        completed_collabs = sum(1 for a in apps if a.get("status") in ["completed", "approved", "paid"])

        # Calculate actual earnings from completed and accepted deals
        total_earnings = 0.0
        for a in apps:
            if a.get("status") in ["accepted", "active", "completed", "approved", "paid"]:
                budget = float(a.get("proposed_budget") or a.get("budget") or 0.0)
                total_earnings += budget

        # If zero campaigns in database, return zero (no fake stats)
        return {
            "available_opportunities": total_opps,
            "new_opportunities": new_opps_count,
            "active_collaborations": active_collabs,
            "completed_collaborations": completed_collabs,
            "total_earnings": round(total_earnings, 2)
        }

    @staticmethod
    async def get_opportunities(
        db,
        user_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch paginated business-generated collaboration opportunities with full business metadata.
        Excludes draft, archived, or deleted records.
        """
        filters = filters or {}
        search = (filters.get("search") or "").strip()
        niche = (filters.get("niche") or "").strip()
        platform = (filters.get("platform") or "").strip()
        location = (filters.get("location") or "").strip()
        collab_type = (filters.get("collaboration_type") or "").strip()
        min_budget = filters.get("min_budget")
        max_budget = filters.get("max_budget")

        # 1. Fetch businesses map for instant metadata lookup
        businesses_cursor = db["businesses"].find({})
        businesses_list = await businesses_cursor.to_list(length=500)
        biz_map = {str(b["_id"]): b for b in businesses_list}
        for b in businesses_list:
            if "id" in b:
                biz_map[str(b["id"])] = b

        # 2. Build Query on Campaigns collection
        query: Dict[str, Any] = {"status": {"$ne": "archived"}}

        if search:
            regex_search = re.compile(re.escape(search), re.IGNORECASE)
            query["$or"] = [
                {"name": regex_search},
                {"goal": regex_search},
                {"objective": regex_search},
                {"targetAudience": regex_search},
                {"strategy": regex_search}
            ]

        if platform and platform.lower() != "all":
            query["platforms"] = {"$regex": re.compile(re.escape(platform), re.IGNORECASE)}

        # Fetch matching campaigns sorted by newest first
        campaigns_cursor = db["campaigns"].find(query).sort("createdAt", -1)
        raw_campaigns = await campaigns_cursor.to_list(length=1000)

        # 3. Check existing applications for current influencer
        applied_map = {}
        if user_id:
            user_apps = await db["campaign_applications"].find({"influencer_id": str(user_id)}).to_list(length=500)
            for a in user_apps:
                applied_map[str(a.get("opportunity_id") or a.get("campaign_id"))] = a.get("status", "applied")

        # 4. Construct opportunity items
        items = []
        for camp in raw_campaigns:
            camp_id = str(camp.get("_id") or camp.get("id"))
            biz_id = str(camp.get("businessId") or camp.get("business_id") or "")
            business = biz_map.get(biz_id, {})

            biz_name = business.get("businessName") or business.get("name") or "Verified Partner Brand"
            biz_logo = business.get("logoUrl") or business.get("business_logo") or None
            biz_category = business.get("industry") or business.get("category") or "Retail & Commerce"
            biz_location = business.get("location") or "India"
            biz_desc = business.get("description") or business.get("primaryGoal") or "Leading consumer brand partner."

            # Campaign properties
            title = camp.get("name") or "Product Showcase & Creator Collaboration"
            desc = camp.get("goal") or camp.get("objective") or "Collaborate with top influencers to promote our product lineup."
            camp_platforms = camp.get("platforms") or ["Instagram", "YouTube"]
            if isinstance(camp_platforms, str):
                camp_platforms = [p.strip() for p in camp_platforms.split(",") if p.strip()]

            # Determine budget
            raw_budget = camp.get("budget")
            budget_val = None
            budget_display = "Barter Collaboration"
            if raw_budget:
                try:
                    num_match = re.search(r'[\d,]+', str(raw_budget))
                    if num_match:
                        parsed_num = float(num_match.group(0).replace(',', ''))
                        budget_val = parsed_num
                        budget_display = f"₹{int(parsed_num):,}"
                except Exception:
                    budget_display = str(raw_budget)

            # Determine collaboration type
            type_val = "Paid" if budget_val and budget_val > 0 else "Barter"
            if "gift" in desc.lower() or "free product" in desc.lower():
                type_val = "Product Promotion"

            # Post-filtering for niche / location / collab_type / budget
            if niche and niche.lower() != "all":
                niche_pattern = niche.lower()
                matches_niche = (
                    niche_pattern in biz_category.lower() or
                    niche_pattern in str(camp.get("targetAudience", "")).lower() or
                    niche_pattern in title.lower() or
                    niche_pattern in desc.lower()
                )
                if not matches_niche:
                    continue

            if location and location.lower() != "all":
                if location.lower() not in biz_location.lower():
                    continue

            if collab_type and collab_type.lower() != "all":
                if collab_type.lower() not in type_val.lower():
                    continue

            if min_budget is not None and budget_val is not None:
                if budget_val < float(min_budget):
                    continue

            if max_budget is not None and budget_val is not None:
                if budget_val > float(max_budget):
                    continue

            created_date = camp.get("createdAt") or camp.get("created_at")
            if isinstance(created_date, str):
                try:
                    created_date = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
                except Exception:
                    created_date = None

            item = {
                "id": camp_id,
                "business": {
                    "id": biz_id,
                    "name": biz_name,
                    "logo": biz_logo,
                    "category": biz_category,
                    "location": biz_location,
                    "description": biz_desc
                },
                "campaign": {
                    "id": camp_id,
                    "title": title,
                    "description": desc,
                    "niche": [biz_category],
                    "platforms": camp_platforms,
                    "collaboration_type": type_val,
                    "budget": budget_val,
                    "budget_display": budget_display,
                    "duration": camp.get("duration") or "1 Month",
                    "target_audience": camp.get("targetAudience") or "Youth & General Consumers",
                    "deliverables": [
                        "1 High-quality 9:16 Instagram Reel",
                        "2 Instagram Story mentions with swipe-up/link sticker",
                        "Usage rights for brand ad promotion"
                    ],
                    "status": camp.get("status") or "active",
                    "created_at": created_date
                },
                "is_applied": camp_id in applied_map,
                "application_status": applied_map.get(camp_id)
            }
            items.append(item)

        # 5. Apply Pagination
        total = len(items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = items[start_idx:end_idx]
        total_pages = max(1, (total + limit - 1) // limit)

        return {
            "items": paginated_items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": total_pages
            }
        }

    @staticmethod
    async def get_opportunity_by_id(db, opportunity_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch full authorized details for a single collaboration opportunity."""
        camp_filter = {"_id": ObjectId(opportunity_id)} if ObjectId.is_valid(opportunity_id) else {"_id": opportunity_id}
        camp = await db["campaigns"].find_one(camp_filter)
        if not camp:
            camp = await db["campaigns"].find_one({"id": opportunity_id})
        if not camp:
            return None

        biz_id = str(camp.get("businessId") or camp.get("business_id") or "")
        biz_filter = {"_id": ObjectId(biz_id)} if ObjectId.is_valid(biz_id) else {"_id": biz_id}
        business = await db["businesses"].find_one(biz_filter) if biz_id else None
        business = business or {}

        camp_id = str(camp.get("_id") or camp.get("id"))
        is_applied = False
        app_status = None
        if user_id:
            existing_app = await db["campaign_applications"].find_one({
                "influencer_id": str(user_id),
                "$or": [{"opportunity_id": camp_id}, {"campaign_id": camp_id}]
            })
            if existing_app:
                is_applied = True
                app_status = existing_app.get("status", "applied")

        biz_name = business.get("businessName") or business.get("name") or "Verified Partner Brand"
        biz_logo = business.get("logoUrl") or business.get("business_logo") or None
        biz_category = business.get("industry") or business.get("category") or "Retail & Commerce"
        biz_location = business.get("location") or "India"

        camp_platforms = camp.get("platforms") or ["Instagram", "YouTube"]
        if isinstance(camp_platforms, str):
            camp_platforms = [p.strip() for p in camp_platforms.split(",") if p.strip()]

        raw_budget = camp.get("budget")
        budget_val = None
        budget_display = "Barter Deal"
        if raw_budget:
            try:
                num_match = re.search(r'[\d,]+', str(raw_budget))
                if num_match:
                    parsed_num = float(num_match.group(0).replace(',', ''))
                    budget_val = parsed_num
                    budget_display = f"₹{int(parsed_num):,}"
            except Exception:
                budget_display = str(raw_budget)

        type_val = "Paid" if budget_val and budget_val > 0 else "Barter"

        return {
            "id": camp_id,
            "business": {
                "id": biz_id,
                "name": biz_name,
                "logo": biz_logo,
                "category": biz_category,
                "location": biz_location,
                "description": business.get("description") or business.get("primaryGoal") or "Leading consumer brand partner."
            },
            "campaign": {
                "id": camp_id,
                "title": camp.get("name") or "Product Showcase & Creator Collaboration",
                "description": camp.get("goal") or camp.get("objective") or "Collaborate with top influencers to promote our product lineup.",
                "niche": [biz_category],
                "platforms": camp_platforms,
                "collaboration_type": type_val,
                "budget": budget_val,
                "budget_display": budget_display,
                "duration": camp.get("duration") or "1 Month",
                "target_audience": camp.get("targetAudience") or "Youth & General Consumers",
                "deliverables": [
                    "1 Dedicated 9:16 vertical Instagram Reel",
                    "2 High-engagement Instagram Stories with product tag",
                    "Authentic review & organic reach"
                ],
                "status": camp.get("status") or "active",
                "created_at": camp.get("createdAt") or camp.get("created_at")
            },
            "is_applied": is_applied,
            "application_status": app_status
        }

    @staticmethod
    async def apply_for_opportunity(db, user_id: str, opportunity_id: str, pitch_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit collaboration proposal from authenticated influencer to business campaign."""
        # 1. Check if already applied
        existing = await db["campaign_applications"].find_one({
            "influencer_id": str(user_id),
            "$or": [{"opportunity_id": opportunity_id}, {"campaign_id": opportunity_id}]
        })
        if existing:
            return {
                "success": True,
                "message": "You have already applied for this collaboration.",
                "application_id": str(existing.get("_id"))
            }

        # 2. Fetch opportunity to retrieve business_id
        camp_filter = {"_id": ObjectId(opportunity_id)} if ObjectId.is_valid(opportunity_id) else {"_id": opportunity_id}
        camp = await db["campaigns"].find_one(camp_filter)
        if not camp:
            camp = await db["campaigns"].find_one({"id": opportunity_id})
        
        business_id = str(camp.get("businessId") or camp.get("business_id") or "") if camp else ""

        # 3. Create Application Record
        application_doc = {
            "opportunity_id": opportunity_id,
            "campaign_id": opportunity_id,
            "business_id": business_id,
            "influencer_id": str(user_id),
            "pitch_message": pitch_data.get("pitch_message", "").strip(),
            "proposed_budget": float(pitch_data.get("proposed_budget") or 0.0),
            "deliverables": pitch_data.get("deliverables") or ["1 Reel", "2 Stories"],
            "status": "applied",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        res = await db["campaign_applications"].insert_one(application_doc)
        return {
            "success": True,
            "message": "Proposal submitted successfully to the brand!",
            "application_id": str(res.inserted_id)
        }

    @staticmethod
    async def get_my_collaborations(db, user_id: str) -> List[Dict[str, Any]]:
        """List all applications and active collaborations for authenticated influencer."""
        cursor = db["campaign_applications"].find({"influencer_id": str(user_id)}).sort("created_at", -1)
        apps = await cursor.to_list(length=100)
        results = []
        for a in apps:
            opp_id = str(a.get("opportunity_id") or a.get("campaign_id") or "")
            opp = await InfluencerService.get_opportunity_by_id(db, opp_id, user_id)
            results.append({
                "id": str(a["_id"]),
                "opportunity_id": opp_id,
                "status": a.get("status", "applied"),
                "pitch_message": a.get("pitch_message", ""),
                "proposed_budget": a.get("proposed_budget", 0),
                "created_at": a.get("created_at"),
                "opportunity": opp
            })
        return results
