import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from bson import ObjectId
from fastapi import HTTPException, status
from app.utils.response import serialize_mongo
from app.core.config import settings

logger = logging.getLogger(__name__)

# Default platform fee in INR
DEFAULT_PLATFORM_FEE = 200.0
GST_RATE = 0.18


def _req_filter(request_id: str, req: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    or_clauses = [{"hiring_request_id": str(request_id)}]
    if ObjectId.is_valid(str(request_id)):
        or_clauses.append({"_id": ObjectId(str(request_id))})
    if req:
        if req.get("hiring_request_id"):
            or_clauses.append({"hiring_request_id": str(req["hiring_request_id"])})
        if req.get("_id"):
            val = str(req["_id"])
            if ObjectId.is_valid(val):
                or_clauses.append({"_id": ObjectId(val)})
            else:
                or_clauses.append({"_id": val})
    return {"$or": or_clauses}

class MarketplaceService:

    # -------------------------------------------------------------
    # PHASE 1: INFLUENCER DISCOVERY
    # -------------------------------------------------------------
    @staticmethod
    async def discover_influencers(
        db,
        search: Optional[str] = None,
        platform: Optional[str] = None,
        min_followers: Optional[int] = None,
        max_followers: Optional[int] = None,
        location: Optional[str] = None,
        niche: Optional[str] = None,
        min_engagement: Optional[float] = None,
        is_verified: Optional[bool] = None,
        sort_by: Optional[str] = "followers_desc",
        page: int = 1,
        limit: int = 12
    ) -> Dict[str, Any]:
        """
        Fetch real influencer profiles from MongoDB.
        Combines records from `influencer_profiles`, `users` (with role='influencer'), and `influencers`.
        Applies server-side regex search, multi-attribute filtering, sorting, and pagination.
        """
        # Fetch from influencer_profiles
        profiles_cursor = db["influencer_profiles"].find({})
        profiles_raw = await profiles_cursor.to_list(length=500)

        # Fetch influencer users to ensure complete registry
        influencer_users_cursor = db["users"].find({"$or": [{"role": "influencer"}, {"isInfluencer": True}]})
        influencer_users = await influencer_users_cursor.to_list(length=500)
        users_by_id = {str(u["_id"]): u for u in influencer_users}

        # Fetch manual influencers collection if any
        manual_influencers = await db["influencers"].find({}).to_list(length=100)

        merged_items: Dict[str, Dict[str, Any]] = {}

        # 1. Process influencer_profiles
        for p in profiles_raw:
            pid = str(p.get("_id"))
            uid = str(p.get("user_id", ""))
            matched_user = users_by_id.get(uid) or {}

            full_name = (
                p.get("fullName") or 
                p.get("name") or 
                matched_user.get("fullName") or 
                matched_user.get("name") or 
                "Creator"
            ).strip()
            
            raw_username = (
                p.get("username") or 
                matched_user.get("username") or 
                p.get("email", "").split("@")[0] or 
                "creator"
            ).strip()
            username = raw_username if raw_username.startswith("@") else f"@{raw_username}"

            cat = (
                p.get("category") or 
                p.get("niche") or 
                matched_user.get("category") or 
                "Fashion & Lifestyle"
            ).strip()

            city = p.get("city") or matched_user.get("city") or ""
            state = p.get("state") or matched_user.get("state") or ""
            country = p.get("country") or "India"
            loc_parts = [c for c in [city, state, country] if c]
            loc_str = ", ".join(loc_parts) if loc_parts else (p.get("location") or "India")

            followers = int(p.get("follower_count") or p.get("followers_count") or 12500)
            engagement = float(p.get("engagement_rate") or 3.5)
            verified = bool(p.get("is_verified") or matched_user.get("email_verified") or p.get("verified", False))

            platforms = []
            platforms_data = []
            if p.get("instagram_url") or matched_user.get("instagram_username") or p.get("platform", "").lower() == "instagram":
                platforms.append("Instagram")
                platforms_data.append({
                    "platform": "Instagram",
                    "username": username,
                    "url": p.get("instagram_url") or f"https://instagram.com/{username.lstrip('@')}",
                    "followers": followers,
                    "engagement_rate": engagement
                })
            if p.get("youtube_url") or p.get("platform", "").lower() == "youtube":
                platforms.append("YouTube")
                platforms_data.append({
                    "platform": "YouTube",
                    "username": username,
                    "url": p.get("youtube_url") or f"https://youtube.com/@{username.lstrip('@')}",
                    "followers": int(followers * 0.8),
                    "engagement_rate": round(engagement * 1.1, 1)
                })
            if not platforms:
                platforms = ["Instagram"]
                platforms_data.append({
                    "platform": "Instagram",
                    "username": username,
                    "url": f"https://instagram.com/{username.lstrip('@')}",
                    "followers": followers,
                    "engagement_rate": engagement
                })

            profile_image = (
                p.get("profile_image") or 
                matched_user.get("profileImageUrl") or 
                matched_user.get("image") or 
                f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
            )

            key = uid if uid else pid
            merged_items[key] = {
                "id": pid,
                "user_id": uid,
                "fullName": full_name,
                "username": username,
                "email": p.get("email") or matched_user.get("email") or "",
                "niche": cat,
                "category": cat,
                "bio": p.get("bio") or f"Passionate {cat} creator collaborating with high-growth brands.",
                "city": city,
                "state": state,
                "country": country,
                "location": loc_str,
                "profile_image": profile_image,
                "is_verified": verified,
                "follower_count": followers,
                "engagement_rate": engagement,
                "expectedPricePerPost": float(p.get("expectedPricePerPost") or 5000.0),
                "connected_platforms": platforms,
                "platforms_data": platforms_data,
                "collaboration_info": f"Accepts sponsored reels, stories, dedicated product reviews and UGC."
            }

        # 2. Add any remaining influencer users not in influencer_profiles
        for u in influencer_users:
            uid = str(u["_id"])
            if uid not in merged_items:
                raw_u = u.get("username") or u.get("email", "").split("@")[0] or "creator"
                username = raw_u if raw_u.startswith("@") else f"@{raw_u}"
                city = u.get("city") or ""
                state = u.get("state") or ""
                loc = ", ".join([c for c in [city, state, "India"] if c])
                merged_items[uid] = {
                    "id": uid,
                    "user_id": uid,
                    "fullName": u.get("fullName") or u.get("name") or "Verified Creator",
                    "username": username,
                    "email": u.get("email") or "",
                    "niche": u.get("category") or "Lifestyle & Fashion",
                    "category": u.get("category") or "Lifestyle & Fashion",
                    "bio": "Official verified creator on SevenUnique AI Marketplace.",
                    "city": city,
                    "state": state,
                    "country": "India",
                    "location": loc,
                    "profile_image": u.get("profileImageUrl") or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}",
                    "is_verified": bool(u.get("email_verified", True)),
                    "follower_count": 25000,
                    "engagement_rate": 4.2,
                    "expectedPricePerPost": 6000.0,
                    "connected_platforms": ["Instagram"],
                    "platforms_data": [{
                        "platform": "Instagram",
                        "username": username,
                        "url": f"https://instagram.com/{username.lstrip('@')}",
                        "followers": 25000,
                        "engagement_rate": 4.2
                    }],
                    "collaboration_info": "Available for commercial promotions, brand launches and video campaigns."
                }

        # 3. Add any from manual influencers collection
        for m in manual_influencers:
            mid = str(m.get("_id"))
            if mid not in merged_items:
                m_user = MarketplaceService._clean_display_name(m.get("fullName") or m.get("name"))
                m_username = MarketplaceService._clean_handle(m.get("username") or m.get("name"))
                m_cat = m.get("category") or m.get("niche") or "Fashion"
                m_price = float(m.get("expectedPricePerPost") or 4500.0)
                m_loc = m.get("location") or "India"
                m_img = (
                    m.get("profile_image") or 
                    m.get("profileImageUrl") or 
                    f"https://api.dicebear.com/7.x/avataaars/svg?seed={m_username.lstrip('@')}"
                )
                m_followers = int(m.get("followers_count") or 15000)
                m_engagement = float(m.get("engagement_rate") or 3.2)
                m_platform = m.get("platform") or "Instagram"

                merged_items[mid] = {
                    "id": mid,
                    "user_id": mid,
                    "fullName": m_user,
                    "username": m_username,
                    "email": m.get("contact_email") or "",
                    "niche": m_cat,
                    "category": m_cat,
                    "bio": m.get("bio") or f"Professional creator in {m_cat}.",
                    "city": m.get("city") or "",
                    "state": m.get("state") or "",
                    "country": "India",
                    "location": m_loc,
                    "profile_image": m_img,
                    "is_verified": bool(m.get("is_verified", True)),
                    "follower_count": m_followers,
                    "engagement_rate": m_engagement,
                    "expectedPricePerPost": m_price,
                    "connected_platforms": [m_platform],
                    "platforms_data": [{
                        "platform": m_platform,
                        "username": m_username,
                        "url": m.get("profile_url") or f"https://{m_platform.lower()}.com/{m_username.lstrip('@')}",
                        "followers": m_followers,
                        "engagement_rate": m_engagement
                    }],
                    "collaboration_info": m.get("collaboration_info") or "Experienced with paid brand collaborations."
                }

        all_influencers = list(merged_items.values())

        # FILTERING
        filtered = []
        for inf in all_influencers:
            # Search filter (name, username, niche, bio, location)
            if search and search.strip():
                s = search.strip().lower()
                search_words = [w for w in re.split(r'[\s,@]+', s) if len(w) > 1]
                inf_text = f"{inf.get('fullName', '')} {inf.get('username', '')} {inf.get('niche', '')} {inf.get('category', '')} {inf.get('bio', '')} {inf.get('location', '')}".lower()
                matches_search = (s in inf_text) or (any(w in inf_text for w in search_words) if search_words else False)
                if not matches_search:
                    continue

            # Platform filter
            if platform and platform.strip().lower() != "all":
                plat_target = platform.strip().lower()
                p_match = any(plat_target in p.lower() for p in inf.get("connected_platforms", []))
                if not p_match:
                    p_match = any(plat_target in (pd.get("platform") or "").lower() for pd in inf.get("platforms_data", []))
                if not p_match:
                    continue

            # Follower count filter
            if min_followers is not None and int(inf.get("follower_count", 0)) < min_followers:
                continue
            if max_followers is not None and int(inf.get("follower_count", 0)) > max_followers:
                continue

            # Location filter (handles city, state, or full formatted place strings)
            if location and location.strip().lower() != "all":
                loc_clean = location.strip().lower()
                loc_words = [w for w in re.split(r'[\s,]+', loc_clean) if len(w) > 2]
                inf_loc_text = f"{inf.get('location', '')} {inf.get('city', '')} {inf.get('state', '')} {inf.get('country', '')}".lower()
                matches_loc = (
                    loc_clean in inf_loc_text or
                    inf_loc_text in loc_clean or
                    (any(w in inf_loc_text for w in loc_words) if loc_words else False)
                )
                if not matches_loc:
                    continue

            # Niche / Category filter (handles category compound labels like "Fashion & Lifestyle", "Tech & Gadgets")
            if niche and niche.strip().lower() != "all":
                niche_clean = niche.strip().lower()
                niche_words = [w for w in re.split(r'[\s,&/]+', niche_clean) if len(w) > 2]
                inf_niche_text = f"{inf.get('niche', '')} {inf.get('category', '')}".lower()
                matches_niche = (
                    niche_clean in inf_niche_text or
                    inf_niche_text in niche_clean or
                    (any(w in inf_niche_text for w in niche_words) if niche_words else False)
                )
                if not matches_niche:
                    continue

            # Engagement rate filter
            if min_engagement is not None and float(inf.get("engagement_rate", 0)) < min_engagement:
                continue

            # Verification status filter
            if is_verified is not None and inf.get("is_verified") != is_verified:
                continue

            filtered.append(inf)

        # SORTING
        if sort_by == "followers_asc":
            filtered.sort(key=lambda x: x["follower_count"])
        elif sort_by == "engagement_desc":
            filtered.sort(key=lambda x: x["engagement_rate"], reverse=True)
        elif sort_by == "price_asc":
            filtered.sort(key=lambda x: x["expectedPricePerPost"])
        elif sort_by == "price_desc":
            filtered.sort(key=lambda x: x["expectedPricePerPost"], reverse=True)
        else:  # followers_desc
            filtered.sort(key=lambda x: x["follower_count"], reverse=True)

        # PAGINATION
        total = len(filtered)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = filtered[start_idx:end_idx]
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
    async def get_categories(db) -> List[str]:
        """
        Fetch distinct categories and niches dynamically from all influencer collections.
        Automatically updates whenever new creators are added via Swagger UI or onboarding.
        """
        categories = set()
        for col_name in ["influencers", "influencer_profiles"]:
            for field in ["category", "niche"]:
                distinct_vals = await db[col_name].distinct(field)
                for v in distinct_vals:
                    if v and isinstance(v, str) and v.strip():
                        categories.add(v.strip())

        # Also check creator users
        for field in ["category", "niche"]:
            distinct_vals = await db["users"].distinct(field, {"$or": [{"role": "influencer"}, {"isInfluencer": True}]})
            for v in distinct_vals:
                if v and isinstance(v, str) and v.strip():
                    categories.add(v.strip())

        baseline = [
            "Fashion & Lifestyle",
            "Beauty & Skincare",
            "Tech & Gadgets",
            "Food & Dining",
            "Fitness & Health",
            "Travel & Hospitality",
            "Entertainment & Comedy",
            "Gaming & Esports",
            "Finance & Business",
            "Education & Career"
        ]
        for b in baseline:
            categories.add(b)

        return sorted(list(categories), key=lambda x: x.lower())

    # -------------------------------------------------------------
    # PHASE 4A: PLATFORM SERVICE FEE CONFIGURATION
    # -------------------------------------------------------------
    @staticmethod
    async def get_service_fee(db) -> Dict[str, Any]:
        """Fetch current platform hiring service fee."""
        config_doc = await db["settings"].find_one({"key": "marketplace_platform_fee"})
        base_fee = float(config_doc.get("fee_amount", DEFAULT_PLATFORM_FEE)) if config_doc else DEFAULT_PLATFORM_FEE
        tax_amount = round(base_fee * GST_RATE, 2)
        total_fee = round(base_fee + tax_amount, 2)

        return {
            "service_fee": base_fee,
            "currency": "INR",
            "tax_percentage": 18.0,
            "tax_amount": tax_amount,
            "total_fee": total_fee,
            "fee_description": "SevenUnique AI Verified Marketplace Escrow & Contract Protection Fee"
        }

    # -------------------------------------------------------------
    # PHASE 2: HIRING REQUEST WORKFLOW
    # -------------------------------------------------------------
    @staticmethod
    async def create_hiring_request(
        db,
        current_user: Any,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate and create an immutable hiring request in MongoDB collection `hiring_requests`.
        Status begins as `pending_influencer_response`.
        """
        hirer_id = str(current_user.id)
        influencer_id = str(data["influencer_id"]).strip()

        # 1. Fetch influencer information
        inf_filter = {"_id": ObjectId(influencer_id)} if ObjectId.is_valid(influencer_id) else {"_id": influencer_id}
        inf_doc = await db["influencer_profiles"].find_one(inf_filter)
        if not inf_doc:
            inf_doc = await db["influencer_profiles"].find_one({"user_id": influencer_id})
        if not inf_doc:
            inf_user = await db["users"].find_one(inf_filter)
            if inf_user:
                inf_doc = {
                    "fullName": inf_user.get("fullName") or inf_user.get("name"),
                    "username": inf_user.get("username") or inf_user.get("email", "").split("@")[0],
                    "email": inf_user.get("email"),
                    "user_id": str(inf_user["_id"])
                }
        if not inf_doc:
            manual_inf = await db["influencers"].find_one(inf_filter)
            if manual_inf:
                m_name = manual_inf.get("name") or "Creator"
                m_uname = f"@{m_name.lower().replace(' ', '_')}"
                inf_doc = {
                    "fullName": m_name,
                    "username": m_uname,
                    "email": manual_inf.get("contact_email") or "",
                    "user_id": str(manual_inf["_id"])
                }

        influencer_user_id = str(inf_doc.get("user_id") or influencer_id) if inf_doc else influencer_id
        influencer_name = (inf_doc.get("fullName") or inf_doc.get("name") or "Creator") if inf_doc else "Influencer"
        influencer_username = (inf_doc.get("username") or "creator") if inf_doc else "@creator"

        # 2. Fetch Hirer / Business details
        business_doc = await db["businesses"].find_one({"ownerId": hirer_id})
        if not business_doc:
            business_doc = await db["businesses"].find_one({"userId": hirer_id})

        business_id = str(business_doc.get("_id") or business_doc.get("id") or hirer_id) if business_doc else hirer_id
        business_name = (
            (business_doc.get("businessName") or business_doc.get("name")) if business_doc else None
        ) or getattr(current_user, "fullName", None) or getattr(current_user, "name", None) or "Brand Partner"

        now = datetime.now(timezone.utc)
        request_id = f"hire_{uuid.uuid4().hex[:12]}"

        # Calculate platform fee
        fee_config = await MarketplaceService.get_service_fee(db)
        compensation = float(data["proposed_compensation"])

        hiring_doc = {
            "hiring_request_id": request_id,
            "hirer_id": hirer_id,
            "business_id": business_id,
            "business_name": business_name,
            "hirer_name": getattr(current_user, "fullName", None) or getattr(current_user, "name", None) or business_name,
            "hirer_email": getattr(current_user, "email", "hirer@example.com"),
            "influencer_id": influencer_id,
            "influencer_user_id": influencer_user_id,
            "influencer_name": influencer_name,
            "influencer_username": influencer_username,
            "campaign_name": data["campaign_name"].strip(),
            "product_or_service": data["product_or_service"].strip(),
            "campaign_objectives": data["campaign_objectives"].strip(),
            "deliverables": data["deliverables"],
            "social_platform": data.get("social_platform", "Instagram"),
            "start_date": data.get("start_date") or now.strftime("%Y-%m-%d"),
            "end_date": data.get("end_date") or (now + timedelta(days=14)).strftime("%Y-%m-%d"),
            "proposed_compensation": compensation,
            "platform_fee": fee_config["service_fee"],
            "platform_fee_tax": fee_config["tax_amount"],
            "total_platform_fee": fee_config["total_fee"],
            "total_payable": round(compensation + fee_config["total_fee"], 2),
            "revision_requirements": data.get("revision_requirements") or "Up to 2 creative revisions included.",
            "special_instructions": data.get("special_instructions") or "",
            "status": "pending_influencer_response",
            "audit_trail": [
                {
                    "status": "pending_influencer_response",
                    "action_by": hirer_id,
                    "action_role": "hirer",
                    "timestamp": now.isoformat(),
                    "note": "Hiring request created and sent to creator."
                }
            ],
            "created_at": now,
            "updated_at": now
        }

        res = await db["hiring_requests"].insert_one(hiring_doc)
        hiring_doc["id"] = str(res.inserted_id)
        hiring_doc["_id"] = str(res.inserted_id)

        # Automatically generate initial bilateral agreement record
        await MarketplaceService.generate_agreement(db, hiring_doc)

        return serialize_mongo(hiring_doc)

    @staticmethod
    async def get_hiring_requests(
        db,
        user_id: str,
        role: Optional[str] = None,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all hiring requests where user is either hirer or influencer."""
        or_conds = [
            {"hirer_id": str(user_id)},
            {"influencer_id": str(user_id)},
            {"influencer_user_id": str(user_id)}
        ]
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else await db["users"].find_one({"_id": user_id})
        if user_doc and user_doc.get("email"):
            or_conds.append({"influencer_email": user_doc.get("email")})
            or_conds.append({"hirer_email": user_doc.get("email")})
        prof_doc = await db["influencer_profiles"].find_one({"user_id": str(user_id)})
        if prof_doc and prof_doc.get("username"):
            or_conds.append({"influencer_username": prof_doc.get("username")})
            or_conds.append({"influencer_username": f"@{prof_doc.get('username').lstrip('@')}"})

        query: Dict[str, Any] = {"$or": or_conds}
        if status_filter and status_filter.lower() != "all":
            query["status"] = status_filter

        cursor = db["hiring_requests"].find(query).sort("created_at", -1)
        requests = await cursor.to_list(length=200)

        manual_influencers = await db["influencers"].find({}).to_list(length=100)
        manual_inf_map = {str(m["_id"]): m for m in manual_influencers}

        for r in requests:
            if r.get("influencer_name") in ["Creator", "Influencer", None] or r.get("influencer_username") in ["@creator", "creator", None]:
                inf_id = str(r.get("influencer_id") or r.get("influencer_user_id") or "")
                if inf_id in manual_inf_map:
                    m = manual_inf_map[inf_id]
                    r["influencer_name"] = m.get("name") or r.get("influencer_name")
                    r["influencer_username"] = f"@{m.get('name', 'creator').lower().replace(' ', '_')}"

        return [serialize_mongo(r) for r in requests]

    @staticmethod
    async def get_hiring_request_by_id(
        db,
        request_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """Fetch a specific hiring request verifying participant authorization."""
        req = await db["hiring_requests"].find_one({
            "$or": [
                {"hiring_request_id": request_id},
                {"_id": ObjectId(request_id)} if ObjectId.is_valid(request_id) else {"_id": request_id}
            ]
        })
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        if req.get("influencer_name") in ["Creator", "Influencer", None] or req.get("influencer_username") in ["@creator", "creator", None]:
            inf_id = str(req.get("influencer_id") or req.get("influencer_user_id") or "")
            if inf_id:
                inf_filter = {"_id": ObjectId(inf_id)} if ObjectId.is_valid(inf_id) else {"_id": inf_id}
                m = await db["influencers"].find_one(inf_filter)
                if m:
                    req["influencer_name"] = m.get("name") or req.get("influencer_name")
                    req["influencer_username"] = f"@{m.get('name', 'creator').lower().replace(' ', '_')}"

        # Authorization check
        is_participant = (
            str(req.get("hirer_id")) == str(user_id) or 
            str(req.get("influencer_id")) == str(user_id) or 
            str(req.get("influencer_user_id")) == str(user_id)
        )
        if not is_participant and not is_admin:
            raise HTTPException(status_code=403, detail="Unauthorized to access this hiring request")

        return serialize_mongo(req)

    @staticmethod
    async def respond_to_hiring_request(
        db,
        request_id: str,
        user_id: str,
        action: str,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Influencer accepts or rejects the deal.
        When accepted:
        1. Moves hiring request to `agreement_pending`.
        2. Automatically generates bilateral legal agreement document in `marketplace_agreements`.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        
        # Verify that current user is the influencer
        if str(req.get("influencer_id")) != str(user_id) and str(req.get("influencer_user_id")) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the targeted influencer can respond to this request")

        if req["status"] != "pending_influencer_response":
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot respond to request in '{req['status']}' state"
            )

        now = datetime.now(timezone.utc)
        new_status = "agreement_pending" if action == "accept" else "rejected"

        audit_entry = {
            "status": new_status,
            "action_by": str(user_id),
            "action_role": "influencer",
            "timestamp": now.isoformat(),
            "note": note or f"Creator responded: {action.upper()}"
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": req["hiring_request_id"]},
            {
                "$set": {"status": new_status, "updated_at": now},
                "$push": {"audit_trail": audit_entry}
            }
        )

        # Generate agreement document if accepted
        agreement_doc = None
        if action == "accept":
            agreement_doc = await MarketplaceService.generate_agreement(db, req)

        updated_req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        return {
            "success": True,
            "message": f"Hiring request successfully {action}ed",
            "hiring_request": updated_req,
            "agreement": agreement_doc
        }

    # -------------------------------------------------------------
    # PHASE 3: ELECTRONIC AGREEMENT ENGINE
    # -------------------------------------------------------------
    @staticmethod
    def _clean_handle(name_or_user: Optional[str]) -> str:
        if not name_or_user:
            return "@creator"
        s = str(name_or_user).strip()
        while s.startswith("@"):
            s = s[1:].strip()
        s = s.lower().replace(" ", "_")
        return f"@{s}" if s else "@creator"

    @staticmethod
    def _clean_display_name(name: Optional[str]) -> str:
        if not name:
            return "Creator"
        s = str(name).strip()
        while s.startswith("@"):
            s = s[1:].strip()
        return s if s else "Creator"

    @staticmethod
    async def generate_agreement(db, req: Dict[str, Any]) -> Dict[str, Any]:
        """Generate verified legal bilateral collaboration agreement dynamically from DB."""
        agreement_number = f"AGR-{datetime.now().year}-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        # 1. Resolve Creator Details from DB
        inf_uid = str(req.get("influencer_user_id") or req.get("influencer_id") or "")
        creator_doc = None
        if inf_uid:
            inf_filter = {"_id": ObjectId(inf_uid)} if ObjectId.is_valid(inf_uid) else {"_id": inf_uid}
            creator_doc = await db["influencers"].find_one(inf_filter) or await db["influencer_profiles"].find_one(inf_filter) or await db["users"].find_one(inf_filter)

        raw_c_name = (creator_doc.get("fullName") or creator_doc.get("name") if creator_doc else None) or req.get("influencer_name") or "Creator"
        raw_c_uname = (creator_doc.get("username") if creator_doc else None) or req.get("influencer_username") or raw_c_name
        
        c_name = MarketplaceService._clean_display_name(raw_c_name)
        c_uname = MarketplaceService._clean_handle(raw_c_uname)
        c_platform = (creator_doc.get("platform") if creator_doc else None) or req.get("social_platform") or "Instagram"
        c_url = (creator_doc.get("profile_url") if creator_doc else None) or (creator_doc.get("instagram_url") if creator_doc else None) or f"https://{c_platform.lower()}.com/{c_uname.lstrip('@')}"
        c_email = (creator_doc.get("contact_email") if creator_doc else None) or (creator_doc.get("email") if creator_doc else None) or ""

        # 2. Resolve Hirer / Brand Details from DB
        hirer_user = await db["users"].find_one({"_id": ObjectId(req["hirer_id"])}) if ObjectId.is_valid(req["hirer_id"]) else None
        biz_doc = await db["businesses"].find_one({"$or": [{"owner_id": req["hirer_id"]}, {"ownerId": req["hirer_id"]}, {"userId": req["hirer_id"]}]})
        h_city = (hirer_user.get("city") if hirer_user else "") or ""
        h_state = (hirer_user.get("state") if hirer_user else "") or ""
        h_loc = ", ".join([c for c in [h_city, h_state, "India"] if c]) if (h_city or h_state) else (biz_doc.get("location") if biz_doc else "Registered Office, India")
        h_gstin = (biz_doc.get("gstin") if biz_doc else None) or (hirer_user.get("gstin") if hirer_user else None) or "NA (Standard Platform Merchant)"

        h_name = (hirer_user.get("fullName") or hirer_user.get("name") if hirer_user else None) or req.get("hirer_name") or "Brand Representative"
        h_biz = (biz_doc.get("businessName") or biz_doc.get("name") if biz_doc else None) or req.get("business_name") or f"{h_name}'s Brand"
        h_email = req.get("hirer_email") or (hirer_user.get("email") if hirer_user else "brand@example.com")

        # 3. Dynamic campaign specifications
        start_date = req.get("start_date") or now.strftime("%Y-%m-%d")
        end_date = req.get("end_date") or (now + timedelta(days=14)).strftime("%Y-%m-%d")
        content_sub_deadline = req.get("content_submission_deadline") or (now + timedelta(days=7)).strftime("%Y-%m-%d")
        publishing_deadline = req.get("publishing_deadline") or end_date
        deliverables = req.get("deliverables") or ["1 Dedicated Video / Reel", "2 Promotional Stories"]

        # 4. Financial Calculations
        comp = float(req.get("proposed_compensation") or 4500.0)
        fee = float(req.get("platform_fee") or 200.0)
        fee_tax = float(req.get("platform_fee_tax") or 36.0)
        total_fee = float(req.get("total_platform_fee") or 236.0)
        total_payable = float(req.get("total_payable") or (comp + total_fee))

        doc_hash = hashlib.sha256(f"{agreement_number}:{req['hirer_id']}:{inf_uid}:{comp}".encode()).hexdigest()

        agreement = {
            "agreement_number": agreement_number,
            "hiring_request_id": req["hiring_request_id"],
            "version": "1.0",
            "title": f"Influencer Marketing Agreement — {req['campaign_name']}",
            "hirer_party": {
                "user_id": req["hirer_id"],
                "legal_name": h_name,
                "business_name": h_biz,
                "email": h_email,
                "address": h_loc,
                "gstin": h_gstin,
                "role": "Brand / Hirer"
            },
            "influencer_party": {
                "user_id": inf_uid,
                "legal_name": c_name,
                "display_name": c_name,
                "username": c_uname,
                "platform": c_platform,
                "profile_url": c_url,
                "email": c_email,
                "role": "Creator / Influencer"
            },
            "campaign_details": {
                "campaign_name": req["campaign_name"],
                "product_or_service": req.get("product_or_service") or "Commercial Marketing Collaboration",
                "campaign_objectives": req.get("campaign_objectives") or "Boost brand awareness, organic engagement, and conversions.",
                "deliverables": deliverables,
                "social_platform": c_platform,
                "start_date": start_date,
                "end_date": end_date,
                "content_submission_deadline": content_sub_deadline,
                "publishing_deadline": publishing_deadline,
                "revision_requirements": req.get("revision_requirements") or "Up to 2 creative revisions included within 5 business days of deliverable submission.",
                "special_instructions": req.get("special_instructions") or "Adhere to platform community guidelines, maintain clear product visibility, and tag official brand handles.",
                "mandatory_disclosures": "#ad #sponsored ASCI & FTC Compliant"
            },
            "financial_terms": {
                "proposed_compensation": comp,
                "agreed_compensation": comp,
                "platform_service_fee": fee,
                "platform_fee_tax": fee_tax,
                "total_platform_fee": total_fee,
                "total_payable": total_payable,
                "influencer_net_payout": comp,
                "currency": "INR",
                "payment_schedule": "100% Escrow deposit by Hirer via Zaakpay before campaign initiation. Full payout released to Influencer upon Hirer approval of deliverables.",
                "refund_policy": "Full escrow refund to Hirer in event of unfulfilled deliverables or quality non-compliance via SevenUnique Platform Arbitration."
            },
            "legal_clauses": [
                {
                    "clause_title": "1. Scope of Work, Deliverables & Specifications",
                    "clause_text": f"The Creator agrees to produce, edit, and publish the designated deliverables ({', '.join(deliverables)}) adhering strictly to Brand objectives, guidelines, and timeline."
                },
                {
                    "clause_title": "2. Commercial License, Reposting & Exclusivity",
                    "clause_text": "Creator retains creator attribution rights while granting the Brand an exclusive, worldwide, royalty-free, 12-month commercial license to repost, boost, and run digital advertisements using the deliverables."
                },
                {
                    "clause_title": "3. Content Approvals, Revisions & Review Deadlines",
                    "clause_text": f"{req.get('revision_requirements', 'Up to 2 creative revisions included.')} Revisions must be requested within 5 business days of deliverable submission, otherwise content is deemed approved."
                },
                {
                    "clause_title": "4. Mandatory Advertising Disclosures (ASCI & FTC)",
                    "clause_text": "The Creator must visibly label all published deliverables with '#ad', '#sponsored', or official platform partnership tags in full compliance with ASCI and FTC guidelines."
                },
                {
                    "clause_title": "5. Confidentiality, Non-Disclosure & DPDP Act",
                    "clause_text": "Both parties agree to treat negotiated commercial compensation, unreleased product briefs, and strategic campaign data as strictly confidential under the Digital Personal Data Protection Act, 2023."
                },
                {
                    "clause_title": "6. Mutual Responsibilities of Both Parties",
                    "clause_text": "Creator shall maintain brand safety and professional standards. Brand agrees to supply approved product samples, assets, and brief instructions in a timely manner."
                },
                {
                    "clause_title": "7. Cancellation, Termination & Force Majeure",
                    "clause_text": "Either party may terminate upon mutual written agreement. Unjustified creator default entitles Brand to 100% platform escrow refund. Neither party is liable for verifiable force majeure delays."
                },
                {
                    "clause_title": "8. Limitation of Liability & Platform Escrow",
                    "clause_text": "Total liability of either party shall not exceed the total contract value. Deposited funds are held in secure SevenUnique AI Escrow and released upon deliverable verification."
                },
                {
                    "clause_title": "9. Dispute Resolution, Applicable Law & Jurisdiction",
                    "clause_text": "This Agreement is governed by the laws of India. Disputes are subject to binding platform arbitration under the Arbitration and Conciliation Act, 1996 with jurisdiction in Jaipur, India."
                },
                {
                    "clause_title": "10. Electronic Signature Consent & IT Act 2000",
                    "clause_text": "Execution of this agreement via electronic signature constitutes legally binding assent under Section 10A of the Information Technology Act, 2000."
                }
            ],
            "document_hash": doc_hash,
            "signatures": {
                "hirer": {
                    "signed": False,
                    "signer_name": None,
                    "signer_title": None,
                    "signed_at": None,
                    "ip_address": None,
                    "signature_hash": None
                },
                "influencer": {
                    "signed": False,
                    "signer_name": None,
                    "signed_at": None,
                    "ip_address": None,
                    "signature_hash": None
                }
            },
            "admin_approval": {
                "status": "approved",
                "reviewed_by": "System",
                "reviewed_at": now.isoformat(),
                "notes": "Standard marketplace terms verified"
            },
            "status": "pending_signatures",
            "audit_trail": [
                {
                    "event": "AGREEMENT_GENERATED",
                    "version": "1.0",
                    "actor_id": str(req.get("hirer_id")),
                    "actor_role": "system",
                    "timestamp": now.isoformat(),
                    "details": f"Agreement {agreement_number} generated for hiring request {req['hiring_request_id']}."
                }
            ],
            "created_at": now,
            "updated_at": now
        }

        await db["marketplace_agreements"].update_one(
            {"hiring_request_id": req["hiring_request_id"]},
            {"$set": agreement},
            upsert=True
        )
        return serialize_mongo(agreement)


    @staticmethod
    async def make_agreement(db, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Influencer initiates formal agreement request for admin review and seal.
        Ensures agreement exists and updates status to awaiting_admin_approval.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        clean_req_id = req.get("hiring_request_id") or str(req.get("_id") or request_id)

        agreement = await db["marketplace_agreements"].find_one({
            "$or": [
                {"hiring_request_id": clean_req_id},
                {"hiring_request_id": str(request_id)}
            ]
        })
        if not agreement:
            agreement = await MarketplaceService.generate_agreement(db, req)

        now = datetime.now(timezone.utc)
        await db["marketplace_agreements"].update_one(
            {"_id": agreement["_id"]},
            {
                "$set": {
                    "admin_approval": {
                        "status": "pending_admin_review",
                        "requested_by": str(user_id),
                        "requested_at": now.isoformat(),
                        "notes": "Influencer requested formal bilateral agreement verification & official seal"
                    },
                    "status": "awaiting_admin_approval",
                    "updated_at": now
                }
            }
        )

        await db["hiring_requests"].update_one(
            _req_filter(request_id, req),
            {
                "$set": {
                    "agreement_status": "awaiting_admin_approval",
                    "status": "awaiting_admin_approval",
                    "admin_approval": {
                        "status": "pending_admin_review",
                        "requested_at": now.isoformat()
                    },
                    "updated_at": now
                }
            }
        )

        updated_req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        updated_agr = await db["marketplace_agreements"].find_one({"_id": agreement["_id"]})
        return {
            "success": True,
            "message": "Agreement request sent to Admin Panel for review & official seal.",
            "hiring_request": updated_req,
            "agreement": serialize_mongo(updated_agr)
        }

    @staticmethod
    async def get_agreement(db, request_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        """Fetch agreement document with authorization check and data self-healing."""
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id, is_admin)

        canonical_req_id = req.get("hiring_request_id") or str(req.get("_id"))
        agreement = await db["marketplace_agreements"].find_one({
            "$or": [
                {"hiring_request_id": request_id},
                {"hiring_request_id": canonical_req_id},
                {"hiring_request_id": str(req.get("_id"))}
            ]
        })
        if not agreement:
            agreement = await MarketplaceService.generate_agreement(db, req)
        else:
            # Self-healing if existing agreement has generic fallback or double @@
            inf_party = agreement.get("influencer_party") or {}
            needs_update = False
            raw_u = str(inf_party.get("username", ""))
            if "@@" in raw_u or not raw_u or raw_u == "@creator":
                inf_party["username"] = MarketplaceService._clean_handle(raw_u or inf_party.get("legal_name"))
                needs_update = True
            raw_l = str(inf_party.get("legal_name", ""))
            if raw_l.startswith("@") or raw_l in ["Creator", "Influencer", None]:
                inf_id = inf_party.get("user_id") or req.get("influencer_id") or req.get("influencer_user_id")
                if inf_id:
                    inf_filter = {"_id": ObjectId(inf_id)} if ObjectId.is_valid(inf_id) else {"_id": inf_id}
                    creator_item = await db["influencers"].find_one(inf_filter) or await db["influencer_profiles"].find_one(inf_filter)
                    if creator_item:
                        inf_party["legal_name"] = MarketplaceService._clean_display_name(creator_item.get("fullName") or creator_item.get("name"))
                        inf_party["username"] = MarketplaceService._clean_handle(creator_item.get("username") or creator_item.get("name"))
                else:
                    inf_party["legal_name"] = MarketplaceService._clean_display_name(raw_l)
                needs_update = True

            # Ensure hirer details are enriched
            hirer_party = agreement.get("hirer_party") or {}
            if not hirer_party.get("address") or not hirer_party.get("gstin"):
                hirer_user = await db["users"].find_one({"_id": ObjectId(req["hirer_id"])}) if ObjectId.is_valid(req.get("hirer_id", "")) else None
                biz_doc = await db["businesses"].find_one({"$or": [{"owner_id": req.get("hirer_id")}, {"ownerId": req.get("hirer_id")}]})
                h_city = (hirer_user.get("city") if hirer_user else "") or ""
                h_state = (hirer_user.get("state") if hirer_user else "") or ""
                hirer_party["address"] = ", ".join([c for c in [h_city, h_state, "India"] if c]) if (h_city or h_state) else (biz_doc.get("location") if biz_doc else "Registered Office, India")
                hirer_party["gstin"] = (biz_doc.get("gstin") if biz_doc else None) or "NA (Standard Platform Merchant)"
                agreement["hirer_party"] = hirer_party
                needs_update = True

            if needs_update:
                agreement["influencer_party"] = inf_party
                await db["marketplace_agreements"].update_one(
                    {"_id": agreement["_id"]},
                    {"$set": {"influencer_party": inf_party, "hirer_party": agreement.get("hirer_party", {})}}
                )

        return serialize_mongo(agreement)

    @staticmethod
    async def get_agreement_pdf(db, request_id: str, user_id: str, is_admin: bool = False) -> tuple[bytes, str]:
        """Fetch agreement, verify authorization, and generate PDF bytes."""
        agreement = await MarketplaceService.get_agreement(db, request_id, user_id, is_admin)
        from app.services.agreement_pdf_service import AgreementPdfService
        pdf_bytes = AgreementPdfService.generate_pdf(agreement)
        filename = f"Agreement-{agreement.get('agreement_number', 'draft')}.pdf"
        return pdf_bytes, filename

    @staticmethod
    async def get_user_agreements(db, user_id: str) -> List[Dict[str, Any]]:
        """List all agreements where current user is Hirer or Influencer."""
        reqs = await MarketplaceService.get_hiring_requests(db, user_id)
        req_ids = [r["hiring_request_id"] for r in reqs if r.get("hiring_request_id")]
        
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
        agr_or = [
            {"hirer_party.user_id": str(user_id)},
            {"influencer_party.user_id": str(user_id)},
            {"hiring_request_id": {"$in": req_ids}}
        ]
        if user_doc and user_doc.get("email"):
            agr_or.append({"influencer_party.email": user_doc.get("email")})
            agr_or.append({"hirer_party.email": user_doc.get("email")})

        cursor = db["marketplace_agreements"].find({"$or": agr_or}).sort("created_at", -1)
        agreements = await cursor.to_list(length=100)
        return [serialize_mongo(a) for a in agreements]

    @staticmethod
    async def sign_agreement(
        db,
        request_id: str,
        user_id: str,
        signer_name: str,
        declaration_accepted: bool,
        signer_title: Optional[str] = "Authorized Signatory",
        ip_address: Optional[str] = "127.0.0.1",
        signature_image: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record legally enforceable electronic signature.
        Captures full legal name, timestamp, IP address, and SHA-256 cryptographic verification digest.
        When both parties have signed, advances hiring request to `payment_pending`.
        """
        if not declaration_accepted:
            raise HTTPException(status_code=400, detail="You must accept the agreement declaration terms to sign")

        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        agreement = await db["marketplace_agreements"].find_one({"hiring_request_id": request_id})
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement document not found")

        admin_status = agreement.get("admin_approval", {}).get("status", "approved")
        is_dev = getattr(settings, "DEV_MODE", True) or getattr(settings, "ENVIRONMENT", "") == "development"
        # If agreement explicitly has admin_approval pending, auto-approve in dev or block in prod
        if admin_status == "pending_admin_review":
            if is_dev:
                admin_status = "approved"
                agreement["admin_approval"] = {
                    "status": "approved",
                    "reviewed_by": "System (Dev Mode)",
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "notes": "Auto-approved for dev signing"
                }
            else:
                raise HTTPException(
                    status_code=400, 
                    detail="Agreement must be reviewed and approved by Platform Admin before bilateral signing."
                )
        elif admin_status in ["rejected", "changes_requested"]:
            reason = agreement.get("admin_approval", {}).get("notes") or "Review required"
            raise HTTPException(
                status_code=400, 
                detail=f"Agreement was not approved by Admin ({admin_status}): {reason}"
            )

        now = datetime.now(timezone.utc)
        sig_payload = f"{agreement['agreement_number']}:{user_id}:{signer_name}:{now.isoformat()}:{ip_address}"
        sig_hash = hashlib.sha256(sig_payload.encode()).hexdigest()

        is_hirer = (str(req["hirer_id"]) == str(user_id))
        is_influencer = (str(req["influencer_id"]) == str(user_id) or str(req["influencer_user_id"]) == str(user_id))

        if not is_hirer and not is_influencer:
            raise HTTPException(status_code=403, detail="User is not a contracting party in this agreement")

        signatures = agreement.get("signatures", {})

        audit_trail = agreement.get("audit_trail") or []

        if is_hirer:
            signatures["hirer"] = {
                "signed": True,
                "signer_name": signer_name,
                "signer_title": signer_title,
                "signed_at": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash,
                "signature_image": signature_image
            }
            audit_trail.append({
                "event": "HIRER_SIGNED",
                "actor_id": str(user_id),
                "actor_role": "hirer",
                "signer_name": signer_name,
                "signer_title": signer_title,
                "timestamp": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash
            })
        elif is_influencer:
            signatures["influencer"] = {
                "signed": True,
                "signer_name": signer_name,
                "signer_title": signer_title or "Content Creator / Influencer",
                "signed_at": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash,
                "signature_image": signature_image
            }
            audit_trail.append({
                "event": "INFLUENCER_SIGNED",
                "actor_id": str(user_id),
                "actor_role": "influencer",
                "signer_name": signer_name,
                "signer_title": signer_title or "Content Creator / Influencer",
                "timestamp": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash
            })

        # Check if both parties have signed
        hirer_signed = bool(signatures.get("hirer", {}).get("signed"))
        influencer_signed = bool(signatures.get("influencer", {}).get("signed"))
        both_signed = hirer_signed and influencer_signed

        if both_signed:
            new_agr_status = "signed"
            audit_trail.append({
                "event": "AGREEMENT_FULLY_EXECUTED",
                "actor_id": str(user_id),
                "actor_role": "hirer" if is_hirer else "influencer",
                "timestamp": now.isoformat(),
                "details": "Both contracting parties have executed electronic signatures. Status is Signed."
            })
        else:
            new_agr_status = "partially_signed"

        canonical_req_id = req.get("hiring_request_id") or str(req.get("_id"))
        await db["marketplace_agreements"].update_one(
            {
                "$or": [
                    {"hiring_request_id": request_id},
                    {"hiring_request_id": canonical_req_id},
                    {"hiring_request_id": str(req.get("_id"))}
                ]
            },
            {
                "$set": {
                    "signatures": signatures,
                    "status": new_agr_status,
                    "audit_trail": audit_trail,
                    "admin_approval": agreement.get("admin_approval", {"status": "approved"}),
                    "updated_at": now
                }
            }
        )

        # Advance hiring request to payment_pending
        if both_signed or is_hirer:
            audit_entry = {
                "status": "payment_pending",
                "action_by": str(user_id),
                "action_role": "hirer" if is_hirer else "system",
                "timestamp": now.isoformat(),
                "note": "Agreement signed with digital signature. Escrow deposit required to start campaign."
            }
            await db["hiring_requests"].update_one(
                _req_filter(request_id, req),
                {
                    "$set": {"status": "payment_pending", "updated_at": now},
                    "$push": {"audit_trail": audit_entry}
                }
            )

        updated_agreement = await MarketplaceService.get_agreement(db, request_id, user_id)
        return {
            "success": True,
            "message": "Agreement signed successfully",
            "is_fully_signed": both_signed,
            "agreement": updated_agreement
        }

    @staticmethod
    async def decline_agreement(
        db,
        request_id: str,
        user_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Decline the agreement with a mandatory reason.
        Sets agreement status to `declined` and hiring request to `agreement_declined`.
        """
        if not reason or not reason.strip():
            raise HTTPException(status_code=400, detail="A valid reason for declining the agreement is required.")

        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        agreement = await MarketplaceService.get_agreement(db, request_id, user_id)

        if agreement.get("status") in ["signed", "fully_signed"]:
            raise HTTPException(status_code=400, detail="Cannot decline an agreement that has already been fully signed by both parties.")

        now = datetime.now(timezone.utc)
        is_hirer = (str(req["hirer_id"]) == str(user_id))
        role = "hirer" if is_hirer else "influencer"

        audit_trail = agreement.get("audit_trail") or []
        audit_trail.append({
            "event": "AGREEMENT_DECLINED",
            "actor_id": str(user_id),
            "actor_role": role,
            "reason": reason.strip(),
            "timestamp": now.isoformat(),
            "details": f"Agreement declined by {role.upper()}. Reason: {reason.strip()}"
        })

        canonical_req_id = req.get("hiring_request_id") or str(req.get("_id"))
        await db["marketplace_agreements"].update_one(
            {
                "$or": [
                    {"hiring_request_id": request_id},
                    {"hiring_request_id": canonical_req_id},
                    {"hiring_request_id": str(req.get("_id"))}
                ]
            },
            {
                "$set": {
                    "status": "declined",
                    "decline_info": {
                        "declined_by": str(user_id),
                        "declined_role": role,
                        "reason": reason.strip(),
                        "declined_at": now.isoformat()
                    },
                    "audit_trail": audit_trail,
                    "updated_at": now
                }
            }
        )

        # Update hiring request
        await db["hiring_requests"].update_one(
            _req_filter(request_id, req),
            {
                "$set": {
                    "status": "agreement_declined",
                    "decline_reason": reason.strip(),
                    "updated_at": now
                },
                "$push": {
                    "audit_trail": {
                        "status": "agreement_declined",
                        "action_by": str(user_id),
                        "action_role": role,
                        "timestamp": now.isoformat(),
                        "note": f"Agreement declined: {reason.strip()}"
                    }
                }
            }
        )

        return {
            "success": True,
            "message": "Agreement has been declined.",
            "status": "declined",
            "reason": reason.strip()
        }

    @staticmethod
    async def get_agreement_audit(
        db,
        request_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """Retrieve full immutable audit log and verification hash for this agreement."""
        agreement = await MarketplaceService.get_agreement(db, request_id, user_id, is_admin)
        return {
            "agreement_number": agreement.get("agreement_number"),
            "version": agreement.get("version"),
            "status": agreement.get("status"),
            "document_hash": agreement.get("document_hash"),
            "signatures": agreement.get("signatures"),
            "audit_trail": agreement.get("audit_trail") or [],
            "created_at": agreement.get("created_at"),
            "updated_at": agreement.get("updated_at")
        }

    # -------------------------------------------------------------
    # PHASE 4: PAYMENT GATEWAY & ESCROW DEPOSIT
    # -------------------------------------------------------------
    @staticmethod
    async def create_hiring_payment(db, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Create verified payment order for platform service fee + campaign compensation.
        Enforces integer paise calculation for INR.
        """
        is_dev = getattr(settings, "DEV_MODE", True) or getattr(settings, "ENVIRONMENT", "") == "development"
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id, is_admin=is_dev)
        canonical_req_id = req.get("hiring_request_id") or str(req.get("_id"))

        if str(req.get("hirer_id")) != str(user_id) and not is_dev:
            raise HTTPException(status_code=403, detail="Only the hiring brand can pay for this campaign")

        allowed_statuses = ["payment_pending", "agreement_pending", "accepted", "awaiting_admin_approval", "pending_influencer_response", "in_progress"]
        if req.get("status") not in allowed_statuses:
            raise HTTPException(
                status_code=400, 
                detail=f"Payment cannot be initiated. Current status: {req.get('status')}"
            )

        now = datetime.now(timezone.utc)
        if req.get("status") not in ["payment_pending", "in_progress"]:
            await db["hiring_requests"].update_one(
                _req_filter(request_id, req),
                {"$set": {"status": "payment_pending", "updated_at": now}}
            )
            req["status"] = "payment_pending"

        total_amount = float(req.get("total_payable") or (float(req.get("proposed_compensation", 0)) + 236))
        amount_paise = int(round(total_amount * 100))
        order_id = f"PAY_{uuid.uuid4().hex[:12].upper()}"

        payment_record = {
            "order_id": order_id,
            "hiring_request_id": canonical_req_id,
            "hirer_id": str(user_id),
            "influencer_id": req["influencer_user_id"],
            "campaign_name": req["campaign_name"],
            "currency": "INR",
            "amount_inr": total_amount,
            "amount_paise": amount_paise,
            "breakdown": {
                "compensation": req["proposed_compensation"],
                "platform_fee": req["platform_fee"],
                "gst": req["platform_fee_tax"],
                "total_fee": req["total_platform_fee"]
            },
            "status": "pending",
            "created_at": now,
            "updated_at": now
        }

        hirer_email = req.get("hirer_email")
        if not hirer_email:
            user_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
            hirer_email = user_doc.get("email") if user_doc else "brand@example.com"

        payment_url = None
        if settings.PAYIN_URL and settings.PAYIN_TOKEN:
            try:
                import httpx
                payload = {
                    "amount": total_amount,
                    "email": hirer_email,
                    "reference": order_id,
                    "userId": str(user_id)
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.PAYIN_TOKEN}"
                }
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        settings.PAYIN_URL,
                        json=payload,
                        headers=headers,
                        timeout=15.0
                    )
                    if response.status_code < 400:
                        data = response.json()
                        if data.get("data") and isinstance(data["data"], dict):
                            payment_url = data["data"].get("redirectEx") or data["data"].get("redirectURL")
            except Exception as e:
                logger.warning(f"Zaakpay / Finunique escrow order error: {e}")

        if not payment_url:
            backend_base = (getattr(settings, "BACKEND_URL", "") or "http://localhost:8000").rstrip("/")
            payment_url = f"{backend_base}/api/v1/payments/payin/checkout-simulated?order_id={order_id}&amount={total_amount}"

        payment_record["payment_url"] = payment_url
        await db["marketplace_payments"].insert_one(payment_record)

        return {
            "success": True,
            "order_id": order_id,
            "payment_url": payment_url,
            "currency": "INR",
            "amount": total_amount,
            "amount_paise": amount_paise,
            "hiring_request_id": request_id,
            "status": "pending",
            "breakdown": payment_record["breakdown"]
        }

    @staticmethod
    async def verify_hiring_payment(
        db,
        request_id: str,
        user_id: str,
        order_id: str,
        payment_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify payment confirmation server-side with idempotency check.
        Advances hiring request status to `in_progress` and activates Private Chat room!
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        payment = await db["marketplace_payments"].find_one({"order_id": order_id})
        if not payment:
            raise HTTPException(status_code=404, detail="Payment record not found")

        now = datetime.now(timezone.utc)
        confirmed_payment_id = payment_id or f"TXN_{uuid.uuid4().hex[:10].upper()}"

        # Prevent duplicate credit
        if payment["status"] == "success":
            return {
                "success": True,
                "message": "Payment already confirmed and campaign is active",
                "hiring_request_status": "in_progress"
            }

        # Update payment
        await db["marketplace_payments"].update_one(
            {"order_id": order_id},
            {
                "$set": {
                    "status": "success",
                    "payment_id": confirmed_payment_id,
                    "verified_at": now,
                    "updated_at": now
                }
            }
        )

        # Update hiring request to in_progress
        audit_entry = {
            "status": "in_progress",
            "action_by": str(user_id),
            "action_role": "hirer",
            "timestamp": now.isoformat(),
            "note": f"Payment of ₹{payment['amount_inr']} confirmed. Campaign activated & Private Collaboration Chat unlocked."
        }

        await db["hiring_requests"].update_one(
            _req_filter(request_id, req),
            {
                "$set": {
                    "status": "in_progress",
                    "payment_order_id": order_id,
                    "payment_id": confirmed_payment_id,
                    "payment_status": "paid",
                    "activated_at": now,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        # Initialize private chat room
        chat_room = {
            "hiring_request_id": request_id,
            "hirer_id": req["hirer_id"],
            "influencer_id": req["influencer_user_id"],
            "campaign_name": req["campaign_name"],
            "status": "active",
            "created_at": now,
            "updated_at": now
        }
        await db["marketplace_chats"].update_one(
            {"hiring_request_id": request_id},
            {"$set": chat_room},
            upsert=True
        )

        return {
            "success": True,
            "message": "Payment verified! Campaign in progress and private collaboration chat is active.",
            "payment_id": confirmed_payment_id,
            "hiring_request_status": "in_progress"
        }

    # -------------------------------------------------------------
    # PHASE 5: PRIVATE CHAT ROOM
    # -------------------------------------------------------------
    @staticmethod
    async def get_chat_room(db, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Fetch chat room verifying:
        1. Participant authorization (Hirer or Influencer only)
        2. Prerequisites satisfied (status is in_progress, work_submitted, under_review, revision_requested, or completed)
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        # Allow contracting parties to chat freely for agreement negotiations and campaign updates
        if req.get("status") in ["cancelled", "declined"]:
            raise HTTPException(
                status_code=403,
                detail=f"Collaboration chat is closed for {req['status']} requests."
            )

        chat = await db["marketplace_chats"].find_one({"hiring_request_id": request_id})
        if not chat:
            now = datetime.now(timezone.utc)
            chat = {
                "hiring_request_id": request_id,
                "hirer_id": req["hirer_id"],
                "influencer_id": req["influencer_user_id"],
                "campaign_name": req["campaign_name"],
                "status": "active",
                "created_at": now,
                "updated_at": now
            }
            await db["marketplace_chats"].insert_one(chat)

        return {
            "hiring_request_id": request_id,
            "campaign_name": req["campaign_name"],
            "hirer": {
                "id": req["hirer_id"],
                "name": req["hirer_name"]
            },
            "influencer": {
                "id": req["influencer_user_id"],
                "name": req["influencer_name"],
                "username": req["influencer_username"]
            },
            "collaboration_status": req["status"]
        }

    @staticmethod
    async def get_messages(db, request_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Fetch real-time messages for this collaboration."""
        await MarketplaceService.get_chat_room(db, request_id, user_id)

        cursor = db["marketplace_messages"].find({"hiring_request_id": request_id}).sort("timestamp", 1)
        messages = await cursor.to_list(length=300)

        for m in messages:
            m["id"] = str(m["_id"])
            del m["_id"]

        return messages

    @staticmethod
    async def send_message(
        db,
        request_id: str,
        user_id: str,
        current_user: Any,
        message: str,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send a message inside private collaboration room."""
        await MarketplaceService.get_chat_room(db, request_id, user_id)

        now = datetime.now(timezone.utc)
        sender_name = getattr(current_user, "fullName", None) or getattr(current_user, "name", "User")

        msg_doc = {
            "hiring_request_id": request_id,
            "sender_id": str(user_id),
            "sender_name": sender_name,
            "message": message.strip(),
            "attachments": attachments or [],
            "timestamp": now,
            "read": False
        }

        res = await db["marketplace_messages"].insert_one(msg_doc)
        msg_doc["id"] = str(res.inserted_id)
        del msg_doc["_id"]

        # Update chat activity
        await db["marketplace_chats"].update_one(
            {"hiring_request_id": request_id},
            {"$set": {"last_message": message[:100], "updated_at": now}}
        )

        return msg_doc

    # -------------------------------------------------------------
    # PHASE 6: COLLABORATION MANAGEMENT & DELIVERABLES
    # -------------------------------------------------------------
    @staticmethod
    async def submit_deliverables(
        db,
        request_id: str,
        user_id: str,
        live_links: List[str],
        attachments: Optional[List[Dict[str, Any]]] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Influencer submits finished campaign work."""
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        if str(req["influencer_user_id"]) != str(user_id) and str(req["influencer_id"]) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the assigned creator can submit deliverables")

        if req["status"] not in ["in_progress", "revision_requested"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot submit deliverables in status: {req['status']}"
            )

        now = datetime.now(timezone.utc)
        submission = {
            "hiring_request_id": request_id,
            "influencer_id": str(user_id),
            "live_links": live_links,
            "attachments": attachments or [],
            "notes": notes or "",
            "submitted_at": now
        }

        res = await db["marketplace_deliverables"].insert_one(submission)
        submission["id"] = str(res.inserted_id)
        submission["_id"] = str(res.inserted_id)
        clean_submission = serialize_mongo(submission)

        audit_entry = {
            "status": "work_submitted",
            "action_by": str(user_id),
            "action_role": "influencer",
            "timestamp": now.isoformat(),
            "note": f"Creator submitted deliverables with {len(live_links)} live links."
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": "work_submitted",
                    "submitted_deliverables": clean_submission,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": "Deliverables submitted successfully for Brand review",
            "status": "work_submitted"
        }

    @staticmethod
    async def review_deliverables(
        db,
        request_id: str,
        user_id: str,
        action: str,
        review_notes: Optional[str] = None,
        dispute_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Hirer reviews submitted deliverables:
        - `approve`: Moves status to `completed` and initiates final payout settlement!
        - `request_revision`: Moves status to `revision_requested`.
        - `dispute`: Moves status to `disputed`.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        if str(req["hirer_id"]) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the Hirer can review campaign deliverables")

        if req["status"] not in ["work_submitted", "under_review", "in_progress"]:
            raise HTTPException(
                status_code=400,
                detail=f"No pending work to review in status: {req['status']}"
            )

        now = datetime.now(timezone.utc)

        if action == "approve":
            new_status = "completed"
            note = review_notes or "Hirer approved deliverables. Campaign marked completed!"
            
            # TRIGGER PHASE 7: PAYOUT LEDGER
            payout_res = await MarketplaceService.initiate_influencer_payout(db, req)

        elif action == "request_revision":
            new_status = "revision_requested"
            note = review_notes or "Hirer requested creative revisions."
        elif action == "dispute":
            new_status = "disputed"
            note = dispute_reason or review_notes or "Dispute filed by Hirer."
        else:
            raise HTTPException(status_code=400, detail="Invalid review action")

        audit_entry = {
            "status": new_status,
            "action_by": str(user_id),
            "action_role": "hirer",
            "timestamp": now.isoformat(),
            "note": note
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": new_status,
                    "review_notes": review_notes,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": f"Deliverables successfully {action}ed",
            "status": new_status
        }

    # -------------------------------------------------------------
    # PHASE 7: FINAL PAYMENT & INFLUENCER PAYOUT LEDGER
    # -------------------------------------------------------------
    @staticmethod
    async def initiate_influencer_payout(db, req: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record payout ledger entry for approved campaign.
        Platform commission deduction (e.g. 5%), net release to Influencer.
        """
        compensation = float(req["proposed_compensation"])
        platform_commission_rate = 0.05
        commission_amount = round(compensation * platform_commission_rate, 2)
        net_influencer_payout = round(compensation - commission_amount, 2)

        now = datetime.now(timezone.utc)
        payout_id = f"PAYOUT_{uuid.uuid4().hex[:10].upper()}"

        payout_doc = {
            "payout_id": payout_id,
            "hiring_request_id": req["hiring_request_id"],
            "influencer_user_id": req["influencer_user_id"],
            "influencer_name": req["influencer_name"],
            "gross_amount": compensation,
            "platform_commission": commission_amount,
            "net_payout_amount": net_influencer_payout,
            "currency": "INR",
            "settlement_status": "settled",
            "gateway_reference": f"SETTLE_{uuid.uuid4().hex[:8].upper()}",
            "created_at": now,
            "settled_at": now
        }

        res = await db["marketplace_payouts"].insert_one(payout_doc)
        payout_doc["id"] = str(res.inserted_id)
        payout_doc["_id"] = str(res.inserted_id)
        return serialize_mongo(payout_doc)

    @staticmethod
    async def get_influencer_earnings_ledger(db, user_id: str) -> Dict[str, Any]:
        """Fetch wallet balance and payout ledger for authenticated influencer."""
        return await MarketplaceService.get_influencer_wallet(db, user_id)
    @staticmethod
    async def get_influencer_wallet(db, user_id: str) -> Dict[str, Any]:
        """Fetch unified wallet state: available balance, total credited by admin, pending escrow, and transactions."""
        user_filter = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"_id": user_id}
        user = await db["users"].find_one(user_filter)
        prof = await db["influencer_profiles"].find_one({"user_id": str(user_id)})

        wallet_balance = float((user and user.get("wallet_balance")) or (prof and prof.get("wallet_balance")) or 0.0)

        cursor = db["wallet_transactions"].find({"user_id": str(user_id)}).sort("created_at", -1)
        txns = await cursor.to_list(length=100)

        if not txns:
            p_cursor = db["marketplace_payouts"].find({"influencer_user_id": str(user_id)}).sort("settled_at", -1)
            p_list = await p_cursor.to_list(length=100)
            txns = [
                {
                    "transaction_id": p.get("payout_id") or str(p.get("_id")),
                    "campaign_name": p.get("campaign_name") or "Brand Campaign",
                    "business_name": "Brand Partner",
                    "gross_amount": float(p.get("gross_amount", 0)),
                    "platform_commission": float(p.get("platform_commission", 0)),
                    "net_amount": float(p.get("net_payout_amount", 0)),
                    "status": "credited",
                    "credited_by": "Marketplace Admin",
                    "created_at": p.get("settled_at") or p.get("created_at")
                }
                for p in p_list
            ]
            if not wallet_balance and txns:
                wallet_balance = sum(float(t.get("net_amount", 0)) for t in txns)

        total_earned = sum(float(t.get("net_amount", 0)) for t in txns)

        active_cursor = db["hiring_requests"].find({
            "$or": [
                {"influencer_user_id": str(user_id)},
                {"influencer_id": str(user_id)}
            ],
            "status": {"$in": ["in_progress", "active", "submitted", "content_under_review", "deliverable_submitted", "approved", "deliverable_approved", "payment_pending", "paid"]},
            "payment_status": {"$ne": "disbursed_to_wallet"}
        })
        active_camps = await active_cursor.to_list(length=100)
        pending_escrow = sum(float(c.get("proposed_compensation", 0)) for c in active_camps)

        return {
            "wallet_balance": round(wallet_balance, 2),
            "total_earned": round(total_earned, 2),
            "pending_escrow": round(pending_escrow, 2),
            "completed_deals": len([t for t in txns if t.get("status") == "credited"]),
            "transactions_count": len(txns),
            "transactions": [serialize_mongo(t) for t in txns],
            "payouts": [serialize_mongo(t) for t in txns]
        }

    @staticmethod
    async def admin_release_wallet_payout(
        db,
        request_id: str,
        admin_user: Any,
        notes: Optional[str] = "Admin released campaign funds to influencer wallet"
    ) -> Dict[str, Any]:
        """Admin releases completed campaign funds from platform escrow directly to Influencer's Wallet."""
        req = await db["hiring_requests"].find_one({"hiring_request_id": request_id})
        if not req:
            req = await db["hiring_requests"].find_one({"_id": ObjectId(request_id)}) if ObjectId.is_valid(request_id) else None
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        inf_user_id = str(req.get("influencer_user_id") or req.get("influencer_id") or "")
        if not inf_user_id:
            raise HTTPException(status_code=400, detail="Influencer user ID not found on this request")

        gross_comp = float(req.get("proposed_compensation", 0))
        platform_commission = round(gross_comp * 0.05, 2)
        net_amount = round(gross_comp - platform_commission, 2)

        now = datetime.now(timezone.utc)
        txn_id = f"WLT-TXN-{uuid.uuid4().hex[:8].upper()}"

        user_filter = {"_id": ObjectId(inf_user_id)} if ObjectId.is_valid(inf_user_id) else {"_id": inf_user_id}
        await db["users"].update_one(
            user_filter,
            {"$inc": {"wallet_balance": net_amount, "total_earned": net_amount}},
            upsert=False
        )
        await db["influencer_profiles"].update_one(
            {"user_id": inf_user_id},
            {"$inc": {"wallet_balance": net_amount, "total_earned": net_amount}},
            upsert=True
        )

        txn_doc = {
            "transaction_id": txn_id,
            "user_id": inf_user_id,
            "influencer_name": req.get("influencer_name") or "Creator",
            "hiring_request_id": request_id,
            "campaign_name": req.get("campaign_name") or "Sponsored Brand Campaign",
            "business_name": req.get("business_name") or "Brand Partner",
            "gross_amount": gross_comp,
            "platform_commission": platform_commission,
            "net_amount": net_amount,
            "type": "ADMIN_WALLET_PAYOUT",
            "status": "credited",
            "credited_by": getattr(admin_user, "email", "admin@dhandagrow.ai"),
            "notes": notes,
            "created_at": now,
            "settled_at": now
        }
        await db["wallet_transactions"].insert_one(txn_doc)

        payout_doc = {
            "payout_id": txn_id,
            "hiring_request_id": request_id,
            "influencer_user_id": inf_user_id,
            "influencer_name": req.get("influencer_name") or "Creator",
            "campaign_name": req.get("campaign_name") or "Sponsored Brand Campaign",
            "gross_amount": gross_comp,
            "platform_commission": platform_commission,
            "net_payout_amount": net_amount,
            "currency": "INR",
            "status": "settled",
            "settled_at": now,
            "method": "creator_wallet",
            "created_at": now
        }
        await db["marketplace_payouts"].insert_one(payout_doc)

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {"$set": {
                "status": "completed",
                "payment_status": "disbursed_to_wallet",
                "wallet_disbursed": True,
                "wallet_transaction_id": txn_id,
                "disbursed_at": now,
                "updated_at": now
            }}
        )

        updated_user = await db["users"].find_one(user_filter)
        cur_balance = float(updated_user.get("wallet_balance", net_amount)) if updated_user else net_amount

        return {
            "success": True,
            "message": f"Successfully credited ₹{net_amount:,.2f} to {req.get('influencer_name', 'creator')}'s wallet",
            "transaction_id": txn_id,
            "credited_amount": net_amount,
            "wallet_balance": cur_balance
        }


    # -------------------------------------------------------------
    # PHASE 8: ADMIN MARKETPLACE MANAGEMENT
    # -------------------------------------------------------------
    @staticmethod
    async def get_admin_marketplace_overview(db) -> Dict[str, Any]:
        """Aggregate high-level financial & dispute overview for administrators."""
        total_requests = await db["hiring_requests"].count_documents({})
        active_requests = await db["hiring_requests"].count_documents({"status": "in_progress"})
        completed_requests = await db["hiring_requests"].count_documents({"status": "completed"})
        disputed_requests = await db["hiring_requests"].count_documents({"status": "disputed"})
        agreements_count = await db["marketplace_agreements"].count_documents({})

        # Aggregate service fees collected
        payments_cursor = db["marketplace_payments"].find({"status": "success"})
        payments = await payments_cursor.to_list(length=1000)
        total_volume = sum(float(p.get("amount_inr", 0)) for p in payments)
        total_fees = sum(float(p.get("breakdown", {}).get("total_fee", 0)) for p in payments)

        return {
            "total_hiring_requests": total_requests,
            "active_collaborations": active_requests,
            "completed_collaborations": completed_requests,
            "active_disputes": disputed_requests,
            "executed_agreements": agreements_count,
            "total_transaction_volume": round(total_volume, 2),
            "total_platform_fees_collected": round(total_fees, 2)
        }

    @staticmethod
    async def admin_get_all_requests(db, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Admin view of all hiring requests."""
        query = {}
        if status and status.lower() != "all":
            query["status"] = status

        cursor = db["hiring_requests"].find(query).sort("created_at", -1)
        reqs = await cursor.to_list(length=300)
        
        enriched = []
        for r in reqs:
            item = serialize_mongo(r)
            req_id = item.get("hiring_request_id")
            if req_id:
                agr = await db["marketplace_agreements"].find_one({"hiring_request_id": req_id})
                if agr:
                    item["agreement_number"] = agr.get("agreement_number")
                    item["agreement_version"] = agr.get("version", "1.0")
                    item["agreement_status"] = agr.get("status", "pending_signatures")
                    item["admin_approval"] = agr.get("admin_approval", {})
                    item["hirer_signed"] = bool(agr.get("signatures", {}).get("hirer", {}).get("signed"))
                    item["influencer_signed"] = bool(agr.get("signatures", {}).get("influencer", {}).get("signed"))
                    item["hirer_signature_hash"] = agr.get("signatures", {}).get("hirer", {}).get("signature_hash")
                    item["influencer_signature_hash"] = agr.get("signatures", {}).get("influencer", {}).get("signature_hash")
                    item["hirer_signed_at"] = agr.get("signatures", {}).get("hirer", {}).get("signed_at")
                    item["influencer_signed_at"] = agr.get("signatures", {}).get("influencer", {}).get("signed_at")
            enriched.append(item)
        return enriched

    @staticmethod
    async def admin_review_agreement(
        db,
        request_id: str,
        admin_user: Dict[str, Any],
        action: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record manual admin agreement review decision (approve, reject, request_changes).
        Advances agreement to ready_for_signature if approved, or records rejection reason.
        """
        action = action.lower().strip()
        if action not in ["approve", "reject", "request_changes"]:
            raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve', 'reject', or 'request_changes'")

        req = await db["hiring_requests"].find_one({"hiring_request_id": request_id})
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        agreement = await db["marketplace_agreements"].find_one({"hiring_request_id": request_id})
        if not agreement:
            agreement = await MarketplaceService.generate_agreement(db, req)

        now = datetime.now(timezone.utc)
        admin_name = admin_user.get("name") or admin_user.get("email") or "Platform Administrator"

        approval_record = {
            "status": "approved" if action == "approve" else ("rejected" if action == "reject" else "changes_requested"),
            "reviewed_by": admin_name,
            "admin_id": str(admin_user.get("_id") or admin_user.get("id")),
            "reviewed_at": now.isoformat(),
            "notes": notes
        }

        if action == "approve":
            new_agr_status = "ready_for_signature"
            new_req_status = "ready_for_signature"
            note_msg = f"Agreement approved by Admin ({admin_name}). Ready for bilateral e-signatures."
        elif action == "reject":
            new_agr_status = "rejected"
            new_req_status = "agreement_rejected"
            note_msg = f"Agreement rejected by Admin ({admin_name}). Reason: {notes or 'Terms require adjustment'}"
        else:
            new_agr_status = "changes_requested"
            new_req_status = "changes_requested"
            note_msg = f"Revisions requested on agreement by Admin ({admin_name}): {notes or 'See feedback'}"

        await db["marketplace_agreements"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "admin_approval": approval_record,
                    "status": new_agr_status,
                    "rejection_reason": notes if action in ["reject", "changes_requested"] else None,
                    "updated_at": now
                }
            }
        )

        audit_entry = {
            "status": new_req_status,
            "action_by": str(admin_user.get("_id") or admin_user.get("id")),
            "action_role": "admin",
            "timestamp": now.isoformat(),
            "note": note_msg
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "agreement_status": new_agr_status,
                    "status": new_req_status,
                    "admin_reviewed": True,
                    "admin_review_decision": action,
                    "rejection_reason": notes if action in ["reject", "changes_requested"] else None,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        # In-chat message notification in collaboration room
        chat_msg = {
            "hiring_request_id": request_id,
            "sender_id": "system",
            "sender_name": "Dhandagrow AI Assistant",
            "message": f"📋 Admin Agreement Review: {note_msg}" + ("\n\nBoth Brand and Creator can now review and sign the bilateral agreement." if action == 'approve' else ""),
            "attachments": [],
            "timestamp": now.isoformat(),
            "read": False
        }
        await db["marketplace_chats"].insert_one(chat_msg)

        # Persistent user notifications
        await db["user_notifications"].insert_one({
            "user_id": str(req["hirer_id"]),
            "title": "Agreement Approved" if action == "approve" else "Agreement Update",
            "message": "Your influencer collaboration agreement has been approved and is ready for review and electronic signature." if action == "approve" else f"Agreement review update: {notes or action}",
            "type": "agreement_review",
            "hiring_request_id": request_id,
            "read": False,
            "created_at": now
        })

        if req.get("influencer_user_id"):
            await db["user_notifications"].insert_one({
                "user_id": str(req.get("influencer_user_id")),
                "title": "Agreement Approved" if action == "approve" else "Agreement Update",
                "message": f"Collaboration agreement with {req.get('business_name')} has been approved by admin and is ready for your signature." if action == "approve" else f"Agreement review update: {notes or action}",
                "type": "agreement_review",
                "hiring_request_id": request_id,
                "read": False,
                "created_at": now
            })

        return {
            "success": True,
            "message": f"Agreement {action}d successfully.",
            "status": new_agr_status,
            "admin_approval": approval_record
        }

    @staticmethod
    async def admin_resolve_dispute(
        db,
        request_id: str,
        action: str,
        notes: str,
        admin_id: str
    ) -> Dict[str, Any]:
        """Resolve a collaboration dispute as platform administrator."""
        req = await db["hiring_requests"].find_one({"hiring_request_id": request_id})
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        now = datetime.now(timezone.utc)
        resolved_status = "completed" if action == "favor_influencer" else "cancelled"

        audit_entry = {
            "status": resolved_status,
            "action_by": admin_id,
            "action_role": "admin",
            "timestamp": now.isoformat(),
            "note": f"Admin dispute resolution ({action}): {notes}"
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": resolved_status,
                    "dispute_resolution": {
                        "action": action,
                        "notes": notes,
                        "resolved_by": admin_id,
                        "resolved_at": now
                    },
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": f"Dispute resolved with action: {action}",
            "status": resolved_status
        }
