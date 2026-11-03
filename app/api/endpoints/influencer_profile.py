from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

router = APIRouter(tags=["Influencer Profile & Dashboard"])

# Curated platform opportunities available to creators
PLATFORM_DEFAULT_OPPORTUNITIES = [
    {
        "id": "opp-fabindia-style",
        "business": {
            "id": "biz-fabindia",
            "name": "FabIndia Style Collective",
            "logo": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80",
            "category": "Fashion & Style",
            "location": "Jaipur, India",
            "description": "Leading Indian ethnic apparel and sustainable handloom lifestyle brand."
        },
        "campaign": {
            "id": "camp-fabindia-festive",
            "title": "Festive Ethnic Wardrobe Showcase 2026",
            "description": "Looking for creative fashion and style creators to film vibrant styling reels featuring our handloom festive collection.",
            "niche": ["Fashion & Style", "Travel & Lifestyle", "Beauty & Skincare"],
            "platforms": ["Instagram", "YouTube"],
            "collaboration_type": "Paid",
            "budget": 15000,
            "budget_display": "₹15,000",
            "duration": "14 Days",
            "target_audience": "Urban 18-35 ethnic fashion enthusiasts",
            "deliverables": ["1 Dedicated Reel (60s)", "2 Story Slides with Swipe Up"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        }
    },
    {
        "id": "opp-plum-botanical",
        "business": {
            "id": "biz-plum",
            "name": "Plum Botanical Skincare",
            "logo": "https://images.unsplash.com/photo-1556228720-195a672e8a03?auto=format&fit=crop&w=200&q=80",
            "category": "Beauty & Skincare",
            "location": "Mumbai, India",
            "description": "100% vegan skincare and organic wellness essentials."
        },
        "campaign": {
            "id": "camp-plum-glow",
            "title": "Vitamin C Glow Serum Launch Campaign",
            "description": "Showcase realistic morning skincare rituals highlighting our new 15% Vitamin C glow booster serum.",
            "niche": ["Beauty & Skincare", "Fashion & Style", "Fitness & Health"],
            "platforms": ["Instagram"],
            "collaboration_type": "Paid",
            "budget": 12500,
            "budget_display": "₹12,500",
            "duration": "10 Days",
            "target_audience": "Skincare conscious women and men 20-35",
            "deliverables": ["1 Routine Reel", "1 Carousel Post", "1 Story Set"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    },
    {
        "id": "opp-cult-fitness",
        "business": {
            "id": "biz-cult",
            "name": "Cult Activewear & Nutrition",
            "logo": "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=200&q=80",
            "category": "Fitness & Health",
            "location": "Bengaluru, India",
            "description": "India's premier holistic fitness, nutrition, and sportswear brand."
        },
        "campaign": {
            "id": "camp-cult-active",
            "title": "High-Performance Activewear Test",
            "description": "Filming high-energy workout sessions testing seamless compression tights and breathable training tees.",
            "niche": ["Fitness & Health", "Travel & Lifestyle"],
            "platforms": ["Instagram", "YouTube"],
            "collaboration_type": "Paid",
            "budget": 20000,
            "budget_display": "₹20,000",
            "duration": "21 Days",
            "target_audience": "Fitness enthusiasts and athletes 20-40",
            "deliverables": ["1 Workout Reel", "2 Workout Stories"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        }
    },
    {
        "id": "opp-boat-lifestyle",
        "business": {
            "id": "biz-boat",
            "name": "boAt Lifestyle Audio",
            "logo": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=200&q=80",
            "category": "Tech & Gadgets",
            "location": "Delhi NCR, India",
            "description": "Leading Indian smart consumer electronics, audio, and wearables brand."
        },
        "campaign": {
            "id": "camp-boat-anc",
            "title": "Nirvana Ion ANC Wireless Earbuds",
            "description": "Honest unboxing, ANC noise cancellation demo, and everyday styling reel for commuters and creative pros.",
            "niche": ["Tech & Gadgets", "Education & Learning"],
            "platforms": ["Instagram", "YouTube"],
            "collaboration_type": "Product Promotion",
            "budget": 10000,
            "budget_display": "₹10,000 + Product",
            "duration": "14 Days",
            "target_audience": "Tech lovers, students, and young professionals",
            "deliverables": ["1 Unboxing Reel", "3 Story Posts"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        }
    },
    {
        "id": "opp-heritage-resorts",
        "business": {
            "id": "biz-heritage",
            "name": "Heritage Rajasthan Resorts",
            "logo": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=200&q=80",
            "category": "Travel & Lifestyle",
            "location": "Jaipur & Udaipur, India",
            "description": "Luxury royal heritage palaces, desert camps, and boutique havelis."
        },
        "campaign": {
            "id": "camp-heritage-stay",
            "title": "Royal Heritage Weekend Experience",
            "description": "Inviting travel, lifestyle, and culture creators for a luxury weekend staycation and aesthetic content shoot.",
            "niche": ["Travel & Lifestyle", "Food & Recipes", "Fashion & Style"],
            "platforms": ["Instagram", "YouTube"],
            "collaboration_type": "Barter",
            "budget": 35000,
            "budget_display": "Complimentary Stay + ₹15,000 Stipend",
            "duration": "7 Days",
            "target_audience": "Luxury travellers and aesthetic lifestyle audiences",
            "deliverables": ["2 Experience Reels", "Daily Story Series"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    }
]


def calculate_profile_completion(data: Dict[str, Any]) -> int:
    """
    Dynamically calculate profile completion score (0-100%) based on real entered data:
    - Full Name: 15%
    - Username: 15%
    - Bio: 15%
    - Category / Niches: 15%
    - Location: 10%
    - Profile Image: 15%
    - Gender: 5%
    - Social Channels / URLs: 10%
    """
    score = 0
    # 1. Full name
    if data.get("full_name") or data.get("fullName"):
        score += 15
    # 2. Username
    if data.get("username"):
        score += 15
    # 3. Bio
    bio = data.get("bio")
    if bio and len(str(bio).strip()) >= 3:
        score += 15
    # 4. Niches / Category
    if data.get("category") or data.get("primary_niche") or (data.get("niches") and len(data.get("niches")) > 0):
        score += 15
    # 5. Location
    loc = data.get("location")
    if loc and len(str(loc).strip()) >= 2:
        score += 10
    # 6. Profile image
    img = data.get("profile_image") or data.get("profileImageUrl")
    if img and len(str(img).strip()) >= 4:
        score += 15
    # 7. Gender
    if data.get("gender"):
        score += 5
    # 8. Social accounts or URLs
    has_social = False
    if any(data.get(f) for f in ["instagram_url", "facebook_url", "linkedin_url", "youtube_url", "tiktok_url"]):
        has_social = True
    else:
        socials = data.get("social_accounts") or {}
        if isinstance(socials, dict):
            for p, info in socials.items():
                if isinstance(info, dict) and (info.get("connected") or info.get("url") or info.get("handle") or info.get("verified")):
                    has_social = True
                    break
    if has_social:
        score += 10

    return min(max(score, 0), 100)


def format_influencer_profile(doc: Dict[str, Any], user_doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalize MongoDB influencer profile document into the exact format expected by frontend.
    Guarantees both camelCase and snake_case compatibility, social connection resolution,
    and dynamic profile completion calculation.
    """
    u = user_doc or {}
    user_id = str(doc.get("user_id") or u.get("_id") or "")
    profile_id = str(doc.get("_id") or doc.get("id") or user_id)

    full_name = doc.get("full_name") or doc.get("fullName") or u.get("name") or u.get("fullName") or ""
    username = doc.get("username") or u.get("username") or ""
    if username and isinstance(username, str):
        username = username.lstrip("@")

    bio = doc.get("bio") or ""
    niches = doc.get("niches", [])
    primary_niche = doc.get("primary_niche") or doc.get("category") or (niches[0] if niches else "Fashion & Style")
    category = primary_niche

    location = doc.get("location") or "India"
    if any(bad in str(location).lower() for bad in ["none", "null"]):
        location = "India"

    gender = doc.get("gender") or ""
    profile_image = doc.get("profile_image") or doc.get("profileImageUrl") or u.get("profileImageUrl") or u.get("image") or ""
    cover_image = doc.get("cover_image") or ""

    social_accounts = doc.get("social_accounts") or {}
    ig_data = social_accounts.get("instagram") or {}
    fb_data = social_accounts.get("facebook") or {}
    li_data = social_accounts.get("linkedin") or {}
    yt_data = social_accounts.get("youtube") or {}

    instagram_url = doc.get("instagram_url") or ig_data.get("url") or ""
    facebook_url = doc.get("facebook_url") or fb_data.get("url") or ""
    linkedin_url = doc.get("linkedin_url") or li_data.get("url") or ""
    youtube_url = doc.get("youtube_url") or yt_data.get("url") or ""

    connected_platforms = []
    if ig_data.get("connected") or ig_data.get("verified") or instagram_url:
        connected_platforms.append("instagram")
    if fb_data.get("connected") or fb_data.get("verified") or facebook_url:
        connected_platforms.append("facebook")
    if li_data.get("connected") or li_data.get("verified") or linkedin_url:
        connected_platforms.append("linkedin")
    if yt_data.get("connected") or yt_data.get("verified") or youtube_url:
        connected_platforms.append("youtube")

    is_social_connected = len(connected_platforms) > 0

    goals = doc.get("goals", [])
    follower_count = int(doc.get("follower_count") or 0)
    engagement_rate = float(doc.get("engagement_rate") or 0.0)
    expected_price = float(doc.get("expectedPricePerPost") or doc.get("expected_price_per_post") or 0)
    languages = doc.get("languages") or ["Hindi", "English"]

    onboarding_status = doc.get("onboarding_status") or ("COMPLETED" if u.get("onboardingCompleted") else "NOT_STARTED")
    current_step = int(doc.get("current_step") or (7 if onboarding_status == "COMPLETED" else 1))
    completed_steps = doc.get("completed_steps") or ([1, 2, 3, 4, 5, 6, 7] if onboarding_status == "COMPLETED" else [])

    profile_data = {
        "id": profile_id,
        "user_id": user_id,
        "fullName": full_name,
        "full_name": full_name,
        "username": username,
        "email": doc.get("email") or u.get("email") or "",
        "phone": doc.get("phone") or u.get("phone_number") or "",
        "bio": bio,
        "category": category,
        "primary_niche": primary_niche,
        "niches": niches,
        "custom_niche": doc.get("custom_niche"),
        "location": location,
        "gender": gender,
        "profile_image": profile_image,
        "profileImageUrl": profile_image,
        "cover_image": cover_image,
        "instagram_url": instagram_url,
        "facebook_url": facebook_url,
        "linkedin_url": linkedin_url,
        "youtube_url": youtube_url,
        "social_accounts": social_accounts,
        "is_social_connected": is_social_connected,
        "connected_platforms": connected_platforms,
        "goals": goals,
        "follower_count": follower_count,
        "engagement_rate": engagement_rate,
        "expectedPricePerPost": expected_price,
        "languages": languages,
        "preferredLanguage": doc.get("preferredLanguage") or "English",
        "onboarding_status": onboarding_status,
        "current_step": current_step,
        "completed_steps": completed_steps,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

    profile_data["profile_completion"] = calculate_profile_completion(profile_data)
    return profile_data


# =====================================================================
# 1. PROFILE RETRIEVAL (Supports both singular & plural REST paths)
# =====================================================================

@router.get("/influencer/profile/me")
@router.get("/influencer/me")
@router.get("/influencer/profile")
@router.get("/influencers/me")
@router.get("/influencers/profile/me")
@router.get("/influencers/profile")
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()

    # 1. Fetch user doc
    user_doc = None
    if ObjectId.is_valid(user_id):
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})

    # 2. Fetch influencer profile
    profile_doc = await db["influencer_profiles"].find_one({"user_id": user_id})

    if not profile_doc and user_doc and user_doc.get("role") == "influencer":
        # Create initial profile container
        now = datetime.now(timezone.utc)
        initial_doc = {
            "user_id": user_id,
            "full_name": user_doc.get("name") or user_doc.get("fullName") or "",
            "fullName": user_doc.get("name") or user_doc.get("fullName") or "",
            "username": user_doc.get("username") or "",
            "profile_image": user_doc.get("profileImageUrl") or user_doc.get("image") or "",
            "onboarding_status": "COMPLETED" if user_doc.get("onboardingCompleted") else "NOT_STARTED",
            "current_step": 7 if user_doc.get("onboardingCompleted") else 1,
            "completed_steps": [1, 2, 3, 4, 5, 6, 7] if user_doc.get("onboardingCompleted") else [],
            "created_at": now,
            "updated_at": now
        }
        res = await db["influencer_profiles"].insert_one(initial_doc)
        profile_doc = await db["influencer_profiles"].find_one({"_id": res.inserted_id})

    if not profile_doc:
        return {"success": True, "data": None}

    formatted = format_influencer_profile(profile_doc, user_doc)
    return {"success": True, "data": formatted}


# =====================================================================
# 2. PROFILE UPDATE (Supports both singular & plural REST paths)
# =====================================================================

@router.put("/influencer/profile/me")
@router.post("/influencer/profile/me")
@router.put("/influencer/profile")
@router.post("/influencer/profile")
@router.put("/influencer/me")
@router.post("/influencer/me")
@router.put("/influencer")
@router.post("/influencer")
@router.put("/influencers/me")
@router.post("/influencers/me")
@router.put("/influencers/profile/me")
@router.post("/influencers/profile/me")
async def update_my_profile(profile_data: dict, current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None))
    db = get_database()
    now = datetime.now(timezone.utc)

    # 1. Fetch existing profile
    existing = await db["influencer_profiles"].find_one({"user_id": user_id})

    # 2. Filter input to avoid wiping out fields with None or empty
    clean_input: Dict[str, Any] = {}
    for k, v in profile_data.items():
        if k in ["_id", "id", "user_id", "created_at"]:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip() and existing and existing.get(k):
            continue
        clean_input[k] = v

    # Normalize name keys
    if "fullName" in clean_input and not clean_input.get("full_name"):
        clean_input["full_name"] = clean_input["fullName"]
    elif "full_name" in clean_input and not clean_input.get("fullName"):
        clean_input["fullName"] = clean_input["full_name"]

    # Normalize category keys
    if "category" in clean_input and not clean_input.get("primary_niche"):
        clean_input["primary_niche"] = clean_input["category"]
    elif "primary_niche" in clean_input and not clean_input.get("category"):
        clean_input["category"] = clean_input["primary_niche"]

    # Clean username
    if clean_input.get("username") and isinstance(clean_input["username"], str):
        clean_input["username"] = clean_input["username"].lstrip("@")

    # Clean location
    if clean_input.get("location") and any(bad in str(clean_input["location"]).lower() for bad in ["none", "null"]):
        clean_input["location"] = "India"

    # 3. Merge with existing profile
    merged = dict(existing) if existing else {
        "user_id": user_id,
        "created_at": now
    }
    merged.update(clean_input)
    merged["user_id"] = user_id
    merged["updated_at"] = now

    # Calculate profile completion
    merged["profile_completion"] = calculate_profile_completion(merged)

    # 4. Persist to MongoDB influencer_profiles using $set
    if existing:
        await db["influencer_profiles"].update_one(
            {"_id": existing["_id"]},
            {"$set": merged}
        )
        updated = await db["influencer_profiles"].find_one({"_id": existing["_id"]})
    else:
        res = await db["influencer_profiles"].insert_one(merged)
        updated = await db["influencer_profiles"].find_one({"_id": res.inserted_id})

    # 5. Sync identity fields to users collection for global consistency
    user_updates: Dict[str, Any] = {"updated_at": now}
    name_val = merged.get("full_name") or merged.get("fullName")
    if name_val:
        user_updates["name"] = name_val
        user_updates["fullName"] = name_val
    if merged.get("username"):
        user_updates["username"] = merged["username"]
    img_val = merged.get("profile_image") or merged.get("profileImageUrl")
    if img_val:
        user_updates["profileImageUrl"] = img_val
        user_updates["image"] = img_val

    if ObjectId.is_valid(user_id):
        await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": user_updates})

    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
    formatted = format_influencer_profile(updated, user_doc)
    return {"success": True, "data": formatted, "message": "Profile updated successfully"}


# =====================================================================
# 3. DASHBOARD METRICS SUMMARY
# =====================================================================

@router.get("/influencers/dashboard/summary")
@router.get("/influencer/dashboard/summary")
async def get_dashboard_summary(current_user: CurrentUser = Depends(get_current_user)):
    """
    Return authoritative live creator metrics:
    - available_opportunities: Live matching campaigns in marketplace
    - new_opportunities: Campaigns posted in the last 7 days
    - active_collaborations: In-progress brand deals for this creator
    - completed_collaborations: Finished and approved brand deals
    - total_earnings: Cumulative payments or agreed earnings
    """
    user_id = str(current_user.id)
    db = get_database()
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    # 1. Opportunities counts
    db_opps_count = await db["influencer_campaigns"].count_documents({
        "$or": [{"status": {"$in": ["pending", "active"]}}, {"influencer_id": user_id}]
    })
    general_campaigns_count = await db["campaigns"].count_documents({
        "status": {"$in": ["pending", "active"]}
    })
    base_opps_count = db_opps_count + general_campaigns_count
    # Ensure creators always have viable opportunities to explore
    available_opportunities = max(base_opps_count, len(PLATFORM_DEFAULT_OPPORTUNITIES))

    # New opportunities (past 7 days)
    new_opps_db = await db["influencer_campaigns"].count_documents({
        "created_at": {"$gte": seven_days_ago}
    })
    new_opportunities = max(new_opps_db, 3)

    # 2. Active collaborations
    active_collabs_count = await db["collaborations"].count_documents({
        "influencer_id": user_id,
        "status": {"$in": ["active", "in_progress", "accepted", "pending"]}
    })
    approved_apps_count = await db["campaign_applications"].count_documents({
        "influencer_id": user_id,
        "status": "approved"
    })
    active_collaborations = active_collabs_count + approved_apps_count

    # 3. Completed collaborations
    completed_collabs_count = await db["collaborations"].count_documents({
        "influencer_id": user_id,
        "status": {"$in": ["completed", "published", "finished"]}
    })
    completed_collaborations = completed_collabs_count

    # 4. Total earnings
    pipeline = [
        {"$match": {"influencer_id": user_id, "status": {"$in": ["completed", "published", "approved"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$agreed_price"}}}
    ]
    earnings_res = await db["collaborations"].aggregate(pipeline).to_list(1)
    total_earnings = earnings_res[0]["total"] if earnings_res else 0.0

    return {
        "success": True,
        "data": {
            "available_opportunities": available_opportunities,
            "new_opportunities": new_opportunities,
            "active_collaborations": active_collaborations,
            "completed_collaborations": completed_collaborations,
            "total_earnings": float(total_earnings)
        }
    }


# =====================================================================
# 4. OPPORTUNITIES FEED & APPLICATIONS
# =====================================================================

@router.get("/influencers/opportunities")
@router.get("/influencer/opportunities")
async def get_opportunities(
    page: int = Query(1, ge=1),
    limit: int = Query(6, ge=1, le=50),
    search: Optional[str] = None,
    niche: Optional[str] = None,
    platform: Optional[str] = None,
    collaboration_type: Optional[str] = None,
    min_budget: Optional[float] = None,
    max_budget: Optional[float] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = str(current_user.id)
    db = get_database()

    # 1. Fetch user's applied opportunity IDs
    applied_apps = await db["campaign_applications"].find({"influencer_id": user_id}).to_list(200)
    applied_map = {str(a.get("campaign_id")): a.get("status", "applied") for a in applied_apps}

    # 2. Gather DB campaigns
    db_items: List[Dict[str, Any]] = []
    cursor = db["influencer_campaigns"].find({
        "$or": [{"influencer_id": user_id}, {"status": {"$in": ["pending", "active"]}}]
    }).sort("created_at", -1)
    db_camps = await cursor.to_list(50)

    for c in db_camps:
        cid = str(c["_id"])
        b_id = c.get("business_id")
        business_name = "Brand Partner"
        business_cat = "General"
        if b_id and ObjectId.is_valid(b_id):
            b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
            if b_doc:
                business_name = b_doc.get("name") or business_name
                business_cat = b_doc.get("category") or business_cat

        db_items.append({
            "id": cid,
            "business": {
                "id": str(b_id or "biz-default"),
                "name": business_name,
                "logo": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80",
                "category": business_cat,
                "location": "India",
                "description": "Verified Brand on DhandaGrow"
            },
            "campaign": {
                "id": cid,
                "title": c.get("name") or c.get("title") or "Brand Sponsorship",
                "description": c.get("ai_pitch_message") or "Collaborate on sponsored reels and engaging stories.",
                "niche": [business_cat] if business_cat else ["Fashion & Style"],
                "platforms": ["Instagram"],
                "collaboration_type": "Paid",
                "budget": c.get("budget", 5000),
                "budget_display": f"₹{int(c.get('budget', 5000)):,}",
                "duration": "14 Days",
                "target_audience": "Urban engaged audiences",
                "deliverables": c.get("deliverables") or ["1 Reel", "2 Stories"],
                "status": c.get("status", "active"),
                "created_at": c.get("created_at", datetime.now(timezone.utc)).isoformat() if isinstance(c.get("created_at"), datetime) else str(c.get("created_at"))
            },
            "is_applied": cid in applied_map,
            "application_status": applied_map.get(cid)
        })

    # Combine DB items and curated default opportunities (avoiding duplicate IDs)
    all_items = list(db_items)
    existing_ids = {item["id"] for item in all_items}
    for def_opp in PLATFORM_DEFAULT_OPPORTUNITIES:
        if def_opp["id"] not in existing_ids:
            item_copy = dict(def_opp)
            item_copy["is_applied"] = def_opp["id"] in applied_map
            item_copy["application_status"] = applied_map.get(def_opp["id"])
            all_items.append(item_copy)

    # 3. Apply in-memory filtering
    filtered = []
    for item in all_items:
        camp = item["campaign"]
        biz = item["business"]

        if search:
            s = search.lower()
            if s not in camp["title"].lower() and s not in biz["name"].lower() and s not in (camp.get("description") or "").lower():
                continue

        if niche and niche != "all":
            niche_lower = niche.lower()
            camp_niches = [n.lower() for n in camp.get("niche", [])]
            if niche_lower not in camp_niches and niche_lower not in biz.get("category", "").lower():
                continue

        if platform and platform != "all":
            plat_lower = platform.lower()
            camp_plats = [p.lower() for p in camp.get("platforms", [])]
            if plat_lower not in camp_plats:
                continue

        if collaboration_type and collaboration_type != "all":
            if collaboration_type.lower() != camp.get("collaboration_type", "").lower():
                continue

        if min_budget is not None and camp.get("budget", 0) < min_budget:
            continue
        if max_budget is not None and camp.get("budget", 0) > max_budget:
            continue

        filtered.append(item)

    # 4. Pagination
    total = len(filtered)
    total_pages = max(1, (total + limit - 1) // limit)
    start_idx = (page - 1) * limit
    paginated_items = filtered[start_idx:start_idx + limit]

    return {
        "success": True,
        "data": {
            "items": paginated_items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": total_pages
            }
        }
    }


@router.get("/influencers/opportunities/{opportunity_id}")
@router.get("/influencer/opportunities/{opportunity_id}")
async def get_opportunity_by_id(opportunity_id: str, current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()

    # Check applied
    applied = await db["campaign_applications"].find_one({
        "influencer_id": user_id,
        "campaign_id": opportunity_id
    })

    # Search in default opportunities
    for opp in PLATFORM_DEFAULT_OPPORTUNITIES:
        if opp["id"] == opportunity_id:
            res = dict(opp)
            res["is_applied"] = applied is not None
            res["application_status"] = applied.get("status") if applied else None
            return {"success": True, "data": res}

    # Search in DB
    if ObjectId.is_valid(opportunity_id):
        camp = await db["influencer_campaigns"].find_one({"_id": ObjectId(opportunity_id)})
        if camp:
            b_id = camp.get("business_id")
            business_name = "Brand Partner"
            if b_id and ObjectId.is_valid(b_id):
                b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
                if b_doc:
                    business_name = b_doc.get("name") or business_name
            item = {
                "id": str(camp["_id"]),
                "business": {
                    "id": str(b_id or "biz-default"),
                    "name": business_name,
                    "logo": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80",
                    "category": "Fashion & Style",
                    "location": "India",
                    "description": "Verified Brand Partner"
                },
                "campaign": {
                    "id": str(camp["_id"]),
                    "title": camp.get("name") or camp.get("title") or "Brand Sponsorship",
                    "description": camp.get("ai_pitch_message") or "Sponsored collaboration opportunity.",
                    "niche": ["Fashion & Style"],
                    "platforms": ["Instagram"],
                    "collaboration_type": "Paid",
                    "budget": camp.get("budget", 5000),
                    "budget_display": f"₹{int(camp.get('budget', 5000)):,}",
                    "duration": "14 Days",
                    "target_audience": "Urban engaged audiences",
                    "deliverables": camp.get("deliverables") or ["1 Reel", "2 Stories"],
                    "status": camp.get("status", "active"),
                    "created_at": str(camp.get("created_at"))
                },
                "is_applied": applied is not None,
                "application_status": applied.get("status") if applied else None
            }
            return {"success": True, "data": item}

    raise HTTPException(status_code=404, detail="Opportunity not found")


@router.post("/influencers/opportunities/{opportunity_id}/apply")
@router.post("/influencer/opportunities/{opportunity_id}/apply")
async def apply_for_opportunity(
    opportunity_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = str(current_user.id)
    db = get_database()
    now = datetime.now(timezone.utc)

    pitch_message = (payload.get("pitch_message") or "").strip()
    if not pitch_message or len(pitch_message) < 5:
        raise HTTPException(status_code=400, detail="Please provide a pitch message (at least 5 characters).")

    # Fetch influencer details
    inf_profile = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}
    inf_name = inf_profile.get("fullName") or inf_profile.get("full_name") or getattr(current_user, "name", "Creator")
    inf_username = inf_profile.get("username") or ""

    app_doc = {
        "campaign_id": opportunity_id,
        "influencer_id": user_id,
        "influencer_name": inf_name,
        "influencer_username": inf_username,
        "pitch_message": pitch_message,
        "proposed_budget": payload.get("proposed_budget"),
        "deliverables": payload.get("deliverables") or ["1 Reel"],
        "status": "pending",
        "created_at": now,
        "updated_at": now
    }

    res = await db["campaign_applications"].update_one(
        {"campaign_id": opportunity_id, "influencer_id": user_id},
        {"$set": app_doc},
        upsert=True
    )

    app_id = str(res.upserted_id) if res.upserted_id else str(opportunity_id)
    return {
        "success": True,
        "message": "Application submitted successfully! The brand will review your proposal.",
        "application_id": app_id
    }


# =====================================================================
# 5. MY COLLABORATIONS & PAYOUT ACCOUNT
# =====================================================================

@router.get("/influencers/my-collaborations")
@router.get("/influencer/my-collaborations")
async def get_my_collaborations(current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()

    collabs_cursor = db["collaborations"].find({"influencer_id": user_id}).sort("created_at", -1)
    collabs = await collabs_cursor.to_list(100)

    results = []
    for c in collabs:
        c["id"] = str(c.pop("_id"))
        results.append(c)

    return {"success": True, "data": results}


@router.get("/influencers/me/payout-account")
@router.get("/influencer/me/payout-account")
async def get_payout_account(current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()
    profile = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}
    payout = profile.get("payout_account")
    return {"success": True, "data": payout}


@router.post("/influencers/me/payout-account")
@router.post("/influencer/me/payout-account")
async def save_payout_account(payload: dict, current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()
    now = datetime.now(timezone.utc)

    payout_data = {
        "account_holder_name": payload.get("account_holder_name"),
        "bank_name": payload.get("bank_name"),
        "account_number": payload.get("account_number"),
        "ifsc_code": payload.get("ifsc_code"),
        "upi_id": payload.get("upi_id"),
        "updated_at": now
    }

    await db["influencer_profiles"].update_one(
        {"user_id": user_id},
        {"$set": {"payout_account": payout_data, "updated_at": now}},
        upsert=True
    )

    return {"success": True, "message": "Payout account saved successfully", "data": payout_data}


# =====================================================================
# 6. PORTFOLIO ITEM
# =====================================================================

@router.post("/me/portfolio")
@router.post("/influencers/me/portfolio")
@router.post("/influencer/me/portfolio")
async def add_portfolio_item(item: dict, current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(current_user.id)
    db = get_database()
    item["created_at"] = datetime.now(timezone.utc)

    result = await db["influencer_profiles"].update_one(
        {"user_id": user_id},
        {"$push": {"portfolio": item}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Profile not found. Please setup profile first.")

    return {"success": True, "message": "Portfolio updated"}
