from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.services.chat_service import ChatService
from app.services.chat_ws_manager import chat_ws_manager
from app.schemas.influencer_dashboard import (
    InfluencerDashboardResponse,
    InfluencerDashboardData,
    CreatorProfileSummary,
    DealSummary,
    BrandOfferSummary,
    EarningsSummary,
    PerformanceMetrics,
    RecentActivityItem
)
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

router = APIRouter(tags=["Influencer Profile & Dashboard"])

# =====================================================================
# BUSINESS CATEGORY TAXONOMY & NORMALIZATION
# =====================================================================

BUSINESS_CATEGORIES = [
    "Café and Restaurant",
    "Boutique and Fashion",
    "Salon and Beauty",
    "Fitness and Gym",
    "Local Shop",
    "Travel and Hospitality",
    "Education and Coaching",
    "Home and Lifestyle",
    "Startup and Other Services"
]

BUSINESS_CATEGORY_MAP = {
    # Café and Restaurant
    "cafe": "Café and Restaurant",
    "café": "Café and Restaurant",
    "restaurant": "Café and Restaurant",
    "café and restaurant": "Café and Restaurant",
    "cafe and restaurant": "Café and Restaurant",
    "food & beverages": "Café and Restaurant",
    "food & recipes": "Café and Restaurant",
    "food and travel": "Café and Restaurant",
    "bakery": "Café and Restaurant",

    # Boutique and Fashion
    "boutique": "Boutique and Fashion",
    "boutique and fashion": "Boutique and Fashion",
    "fashion & apparel": "Boutique and Fashion",
    "fashion & clothing": "Boutique and Fashion",
    "fashion & style": "Boutique and Fashion",
    "fashion & lifestyle": "Boutique and Fashion",
    "jewellery": "Boutique and Fashion",

    # Salon and Beauty
    "salon": "Salon and Beauty",
    "salon and beauty": "Salon and Beauty",
    "salon & beauty": "Salon and Beauty",
    "salon & spa": "Salon and Beauty",
    "beauty & skincare": "Salon and Beauty",
    "beauty & personal care": "Salon and Beauty",
    "haircare": "Salon and Beauty",

    # Fitness and Gym
    "fitness": "Fitness and Gym",
    "gym": "Fitness and Gym",
    "fitness and gym": "Fitness and Gym",
    "fitness & gym": "Fitness and Gym",
    "fitness & health": "Fitness and Gym",

    # Local Shop
    "local shop": "Local Shop",
    "local_shop": "Local Shop",
    "retail": "Local Shop",
    "grocery & supermarket": "Local Shop",
    "handlooms & crafts": "Local Shop",

    # Travel and Hospitality
    "travel": "Travel and Hospitality",
    "hospitality": "Travel and Hospitality",
    "travel and hospitality": "Travel and Hospitality",
    "travel & hospitality": "Travel and Hospitality",
    "travel & lifestyle": "Travel and Hospitality",
    "hotels & resorts": "Travel and Hospitality",
    "entertainment & leisure": "Travel and Hospitality",

    # Education and Coaching
    "education": "Education and Coaching",
    "coaching": "Education and Coaching",
    "education and coaching": "Education and Coaching",
    "education & coaching": "Education and Coaching",
    "education & learning": "Education and Coaching",

    # Home and Lifestyle
    "home and lifestyle": "Home and Lifestyle",
    "home & lifestyle": "Home and Lifestyle",
    "furniture & home": "Home and Lifestyle",
    "home & living": "Home and Lifestyle",

    # Startup and Other Services
    "startup": "Startup and Other Services",
    "startup and other services": "Startup and Other Services",
    "startup & other services": "Startup and Other Services",
    "tech": "Startup and Other Services",
    "tech & gadgets": "Startup and Other Services",
    "tech & gaming": "Startup and Other Services",
    "tech & electronics": "Startup and Other Services",
    "saas / software development": "Startup and Other Services",
    "other business / services": "Startup and Other Services",
    "general": "Startup and Other Services",
    "doctor": "Startup and Other Services",
    "healthcare & clinic": "Startup and Other Services"
}

def normalize_business_category(cat: Optional[str]) -> str:
    """Normalize any database or input category to one of the 9 standard business categories."""
    if not cat:
        return "Boutique and Fashion"
    c_lower = str(cat).strip().lower()
    return BUSINESS_CATEGORY_MAP.get(c_lower, cat)

def canonical_collaboration_status(status_str: Optional[str]) -> str:
    """Normalize any collaboration status into official uppercase enum."""
    if not status_str:
        return "REQUESTED"
    s = str(status_str).strip().upper()
    mapping = {
        "PENDING": "REQUESTED",
        "APPLIED": "REQUESTED",
        "REQUESTED": "REQUESTED",
        "ACCEPTED": "ACCEPTED",
        "ACTIVE": "IN_PROGRESS",
        "IN_PROGRESS": "IN_PROGRESS",
        "CONTENT_SUBMITTED": "PENDING_REVIEW",
        "REVISION_REQUESTED": "PENDING_REVIEW",
        "PENDING_REVIEW": "PENDING_REVIEW",
        "CHANGES_REQUESTED": "PENDING_REVIEW",
        "APPROVED": "COMPLETED",
        "PUBLISHED": "COMPLETED",
        "COMPLETED": "COMPLETED",
        "FINISHED": "COMPLETED",
        "REJECTED": "REJECTED",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED"
    }
    return mapping.get(s, s)


# =====================================================================
# CURATED SMALL BUSINESS OPPORTUNITIES ACROSS ALL 9 CATEGORIES
# =====================================================================

PLATFORM_DEFAULT_OPPORTUNITIES = [
    {
        "id": "opp-chai-bistro",
        "business": {
            "id": "biz-chai-bistro",
            "name": "Chai & Conversations Bistro Café",
            "logo": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=200&q=80",
            "category": "Café and Restaurant",
            "location": "Jaipur, India",
            "description": "Artisan specialty tea house, breakfast café and dessert lounge."
        },
        "campaign": {
            "id": "camp-chai-bistro",
            "title": "Aesthetic Evening Café Ambience & Monsoon Menu",
            "description": "Looking for lifestyle and food creators to capture the cozy cafe ambience, gourmet chai pairings, and signature artisan bakery items.",
            "niche": ["Café and Restaurant", "Food & Recipes", "Travel & Lifestyle"],
            "platforms": ["Instagram"],
            "collaboration_type": "Barter + Paid",
            "budget": 4500,
            "budget_display": "₹4,500 + Meal for Two",
            "duration": "10 Days",
            "target_audience": "Local youth, foodies, and cafe lovers in Jaipur",
            "deliverables": ["1 Aesthetic Reel (30-60s)", "2 Story Slides with Location Tag"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        }
    },
    {
        "id": "opp-fabindia-style",
        "business": {
            "id": "biz-fabindia",
            "name": "Zari Heritage Boutique",
            "logo": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80",
            "category": "Boutique and Fashion",
            "location": "Jaipur, India",
            "description": "Handcrafted ethnic apparel, block print collections, and festive designer wear."
        },
        "campaign": {
            "id": "camp-fabindia-festive",
            "title": "Festive Ethnic Wardrobe Showcase 2026",
            "description": "Looking for creative fashion and style creators to film vibrant styling reels featuring our handloom festive collection.",
            "niche": ["Boutique and Fashion", "Travel & Lifestyle"],
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
        "id": "opp-glam-salon",
        "business": {
            "id": "biz-glam-salon",
            "name": "Glam & Glow Unisex Salon & Spa",
            "logo": "https://images.unsplash.com/photo-1560066984-138dadb4c035?auto=format&fit=crop&w=200&q=80",
            "category": "Salon and Beauty",
            "location": "Mumbai, India",
            "description": "Premier unisex hair styling studio, organic facial treatments, and modern spa rituals."
        },
        "campaign": {
            "id": "camp-glam-glow",
            "title": "Keratin & Glow Facial Transformation Experience",
            "description": "Document your complete salon makeover ritual including hair treatment and revitalizing glass-skin facial.",
            "niche": ["Salon and Beauty", "Boutique and Fashion"],
            "platforms": ["Instagram"],
            "collaboration_type": "Barter + Paid",
            "budget": 6000,
            "budget_display": "₹6,000 + Luxury Treatment",
            "duration": "7 Days",
            "target_audience": "Urban grooming and self-care enthusiasts",
            "deliverables": ["1 Before/After Transformation Reel", "3 Stories"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    },
    {
        "id": "opp-cult-fitness",
        "business": {
            "id": "biz-cult",
            "name": "IronFit Power Gym & CrossFit",
            "logo": "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=200&q=80",
            "category": "Fitness and Gym",
            "location": "Bengaluru, India",
            "description": "High-intensity functional training studio, strength equipment, and certified sports nutrition."
        },
        "campaign": {
            "id": "camp-cult-active",
            "title": "High-Performance 30-Day Fitness Challenge",
            "description": "Filming high-energy workout sessions testing strength facilities and highlighting community coaching.",
            "niche": ["Fitness and Gym", "Home and Lifestyle"],
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
        "id": "opp-local-handlooms",
        "business": {
            "id": "biz-local-handlooms",
            "name": "Jaipur Royal Handlooms & Crafts",
            "logo": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80",
            "category": "Local Shop",
            "location": "Jaipur, India",
            "description": "Local artisan collective offering authentic blue pottery, handmade block prints, and wooden decor."
        },
        "campaign": {
            "id": "camp-local-crafts",
            "title": "Shop Local: Artisan Craftsmanship & Blue Pottery Walkthrough",
            "description": "Showcase authentic Indian artisan handcrafted items and encourage shopping from verified local shop owners.",
            "niche": ["Local Shop", "Home and Lifestyle"],
            "platforms": ["Instagram"],
            "collaboration_type": "Paid",
            "budget": 8000,
            "budget_display": "₹8,000",
            "duration": "14 Days",
            "target_audience": "Conscious shoppers and lovers of traditional arts",
            "deliverables": ["1 Store Walkthrough Reel", "2 Product Stories"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    },
    {
        "id": "opp-heritage-resorts",
        "business": {
            "id": "biz-heritage",
            "name": "Heritage Haveli Staycation & Suites",
            "logo": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=200&q=80",
            "category": "Travel and Hospitality",
            "location": "Jaipur & Udaipur, India",
            "description": "Luxury royal heritage palaces, desert camps, and boutique havelis."
        },
        "campaign": {
            "id": "camp-heritage-stay",
            "title": "Royal Heritage Weekend Experience",
            "description": "Inviting travel, lifestyle, and culture creators for a luxury weekend staycation and aesthetic content shoot.",
            "niche": ["Travel and Hospitality", "Café and Restaurant"],
            "platforms": ["Instagram", "YouTube"],
            "collaboration_type": "Barter + Paid",
            "budget": 35000,
            "budget_display": "Complimentary Stay + ₹15,000",
            "duration": "7 Days",
            "target_audience": "Luxury travellers and aesthetic lifestyle audiences",
            "deliverables": ["2 Experience Reels", "Daily Story Series"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    },
    {
        "id": "opp-apex-academy",
        "business": {
            "id": "biz-apex-academy",
            "name": "Apex Skills & Coaching Academy",
            "logo": "https://images.unsplash.com/photo-1524178232363-1fb2b075b655?auto=format&fit=crop&w=200&q=80",
            "category": "Education and Coaching",
            "location": "Delhi NCR, India",
            "description": "Professional upskilling, civil services coaching, and modern digital career programs."
        },
        "campaign": {
            "id": "camp-apex-coaching",
            "title": "Next-Gen Career Upskilling & Free Masterclass",
            "description": "Educate students and fresh graduates on high-demand AI, finance, and career development skills.",
            "niche": ["Education and Coaching", "Startup and Other Services"],
            "platforms": ["Instagram", "YouTube", "LinkedIn"],
            "collaboration_type": "Paid",
            "budget": 12000,
            "budget_display": "₹12,000",
            "duration": "14 Days",
            "target_audience": "Students, job seekers, and young professionals 18-28",
            "deliverables": ["1 Educational Reel", "1 Carousel Guide", "1 Story Set"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        }
    },
    {
        "id": "opp-jaipur-furnishings",
        "business": {
            "id": "biz-jaipur-furnishings",
            "name": "Jaipur Furnishings & Living Studio",
            "logo": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?auto=format&fit=crop&w=200&q=80",
            "category": "Home and Lifestyle",
            "location": "Jaipur, India",
            "description": "Modern solid wood furniture, bespoke home decor, curtains, and luxury living essentials."
        },
        "campaign": {
            "id": "camp-jaipur-living",
            "title": "Minimalist Living Room Makeover Showcase",
            "description": "Capture realistic room transformations using contemporary wooden furniture and warm ambient home decor.",
            "niche": ["Home and Lifestyle", "Boutique and Fashion"],
            "platforms": ["Instagram"],
            "collaboration_type": "Paid",
            "budget": 18000,
            "budget_display": "₹18,000",
            "duration": "14 Days",
            "target_audience": "Homeowners, interior lovers, and newlyweds 24-45",
            "deliverables": ["1 Living Room Tour Reel", "2 Interior Stories"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        }
    },
    {
        "id": "opp-bytecraft-tech",
        "business": {
            "id": "biz-bytecraft-tech",
            "name": "ByteCraft Cloud Tech & Tools",
            "logo": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=200&q=80",
            "category": "Startup and Other Services",
            "location": "Pune, India",
            "description": "SaaS productivity tools, cloud billing, and AI business management software."
        },
        "campaign": {
            "id": "camp-bytecraft-tools",
            "title": "Automate Your Small Business with AI Tools",
            "description": "Create engaging, practical workflow walkthroughs demonstrating how local shop owners and startups save 10+ hours a week.",
            "niche": ["Startup and Other Services", "Education and Coaching"],
            "platforms": ["Instagram", "LinkedIn"],
            "collaboration_type": "Paid",
            "budget": 14000,
            "budget_display": "₹14,000",
            "duration": "14 Days",
            "target_audience": "Entrepreneurs, creators, and MSME business owners",
            "deliverables": ["1 Problem-Solution Reel", "1 LinkedIn Showcase Post"],
            "status": "active",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        }
    }
]


# =====================================================================
# DYNAMIC PROFILE COMPLETION
# =====================================================================

def calculate_profile_completion(data: Dict[str, Any]) -> int:
    score = 0
    if data.get("full_name") or data.get("fullName"):
        score += 15
    if data.get("username"):
        score += 15
    bio = data.get("bio")
    if bio and len(str(bio).strip()) >= 3:
        score += 15
    if data.get("category") or data.get("primary_niche") or (data.get("niches") and len(data.get("niches")) > 0):
        score += 15
    loc = data.get("location")
    if loc and len(str(loc).strip()) >= 2:
        score += 10
    img = data.get("profile_image") or data.get("profileImageUrl")
    if img and len(str(img).strip()) >= 4:
        score += 15
    if data.get("gender"):
        score += 5

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
    u = user_doc or {}
    user_id = str(doc.get("user_id") or u.get("_id") or "")
    profile_id = str(doc.get("_id") or doc.get("id") or user_id)

    full_name = doc.get("full_name") or doc.get("fullName") or u.get("name") or u.get("fullName") or ""
    username = doc.get("username") or u.get("username") or ""
    if username and isinstance(username, str):
        username = username.lstrip("@")

    bio = doc.get("bio") or ""
    niches = doc.get("niches", [])
    primary_niche = doc.get("primary_niche") or doc.get("category") or (niches[0] if niches else "Boutique and Fashion")
    category = normalize_business_category(primary_niche)

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

    followers = doc.get("follower_count") or doc.get("followers") or 25000
    engagement_rate = doc.get("engagement_rate") or 4.2
    profile_completion = calculate_profile_completion(doc)

    return {
        "id": profile_id,
        "user_id": user_id,
        "fullName": full_name,
        "full_name": full_name,
        "username": username,
        "bio": bio,
        "niches": niches if niches else [primary_niche],
        "primary_niche": primary_niche,
        "category": category,
        "location": location,
        "gender": gender,
        "profileImageUrl": profile_image,
        "profile_image": profile_image,
        "coverImageUrl": cover_image,
        "cover_image": cover_image,
        "instagram_url": instagram_url,
        "facebook_url": facebook_url,
        "linkedin_url": linkedin_url,
        "youtube_url": youtube_url,
        "social_accounts": social_accounts,
        "followers": followers,
        "follower_count": followers,
        "engagement_rate": engagement_rate,
        "profile_completion": profile_completion,
        "profileCompletion": profile_completion,
        "onboarding_status": doc.get("onboarding_status", "COMPLETED"),
        "onboardingCompleted": doc.get("onboardingCompleted", True),
        "status": doc.get("status", "ACTIVE")
    }


# =====================================================================
# 1. PROFILE RETRIEVAL
# =====================================================================

@router.get("/influencer/profile/me")
@router.get("/influencer/profile")
@router.get("/influencer/me")
@router.get("/influencer")
@router.get("/influencers/me")
@router.get("/influencers/profile/me")
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None))
    db = get_database()

    user_doc = None
    if ObjectId.is_valid(user_id):
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        user_doc = await db["users"].find_one({"$or": [{"_id": user_id}, {"id": user_id}]})

    profile_doc = await db["influencer_profiles"].find_one({"user_id": user_id})
    if not profile_doc and ObjectId.is_valid(user_id):
        profile_doc = await db["influencer_profiles"].find_one({"_id": ObjectId(user_id)})

    if not profile_doc:
        now = datetime.now(timezone.utc)
        u_name = (user_doc.get("name") if user_doc else None) or (user_doc.get("fullName") if user_doc else None) or ""
        u_user = (user_doc.get("username") if user_doc else None) or ""
        initial_doc = {
            "user_id": user_id,
            "full_name": u_name,
            "fullName": u_name,
            "username": u_user,
            "category": "Boutique and Fashion",
            "location": "India",
            "bio": "",
            "social_accounts": {},
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now
        }
        res = await db["influencer_profiles"].insert_one(initial_doc)
        profile_doc = await db["influencer_profiles"].find_one({"_id": res.inserted_id})

    formatted = format_influencer_profile(profile_doc, user_doc)
    return {"success": True, "data": formatted}


# =====================================================================
# 2. PROFILE UPDATE
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

    existing = await db["influencer_profiles"].find_one({"user_id": user_id})

    clean_input: Dict[str, Any] = {}
    for k, v in profile_data.items():
        if k in ["_id", "id", "user_id", "created_at"]:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip() and existing and existing.get(k):
            continue
        clean_input[k] = v

    if "fullName" in clean_input and not clean_input.get("full_name"):
        clean_input["full_name"] = clean_input["fullName"]
    elif "full_name" in clean_input and not clean_input.get("fullName"):
        clean_input["fullName"] = clean_input["full_name"]

    if "category" in clean_input and not clean_input.get("primary_niche"):
        clean_input["primary_niche"] = clean_input["category"]
    elif "primary_niche" in clean_input and not clean_input.get("category"):
        clean_input["category"] = clean_input["primary_niche"]

    if clean_input.get("username") and isinstance(clean_input["username"], str):
        clean_input["username"] = clean_input["username"].lstrip("@")

    if clean_input.get("location") and any(bad in str(clean_input["location"]).lower() for bad in ["none", "null"]):
        clean_input["location"] = "India"

    merged = dict(existing) if existing else {
        "user_id": user_id,
        "created_at": now
    }
    merged.update(clean_input)
    merged["user_id"] = user_id
    merged["updated_at"] = now
    merged["profile_completion"] = calculate_profile_completion(merged)

    if existing:
        await db["influencer_profiles"].update_one(
            {"_id": existing["_id"]},
            {"$set": merged}
        )
        updated = await db["influencer_profiles"].find_one({"_id": existing["_id"]})
    else:
        res = await db["influencer_profiles"].insert_one(merged)
        updated = await db["influencer_profiles"].find_one({"_id": res.inserted_id})

    # Sync identity fields to users collection for global consistency
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
# 3. DYNAMIC INFLUENCER DASHBOARD API
# =====================================================================

@router.get("/influencer/dashboard", response_model=InfluencerDashboardResponse)
@router.get("/influencers/dashboard", response_model=InfluencerDashboardResponse)
async def get_influencer_dashboard(current_user: CurrentUser = Depends(get_current_user)):
    """
    Return comprehensive authenticated creator dashboard data:
    - Profile and verification status (UNVERIFIED, PENDING, VERIFIED)
    - Social account status
    - Active collaborations count & collaboration requests count
    - Real earnings from database
    - Dynamic profile completion percentage
    - Recommended business opportunities across local businesses & small enterprises
    - Active collaborations list
    - Performance metrics (reach, engagement, completed count, active count, acceptance rate)
    - Recent activity timeline from real events
    - Live unread chat count
    """
    user_id = str(current_user.id)
    db = get_database()
    now = datetime.now(timezone.utc)

    # 1. Fetch user doc and creator profile doc
    user_doc = None
    if ObjectId.is_valid(user_id):
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        user_doc = await db["users"].find_one({"$or": [{"_id": user_id}, {"id": user_id}]}) or {}

    profile_doc = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}

    # Verification status check across social connections
    connected_platforms = []
    has_verified = False
    has_pending = False
    social_account_status: Dict[str, Any] = {}

    for col_name, plat_name in [
        ("instagram_connections", "instagram"),
        ("facebook_connections", "facebook"),
        ("linkedin_connections", "linkedin")
    ]:
        conn = await db[col_name].find_one({"user_id": user_id})
        if conn:
            c_status = (conn.get("status") or "NOT_CONNECTED").upper()
            social_account_status[plat_name] = {
                "connected": c_status in ["VERIFIED", "PENDING"],
                "status": c_status,
                "platform_account_id": conn.get("platform_account_id"),
                "username": conn.get("username")
            }
            if c_status == "VERIFIED":
                has_verified = True
                connected_platforms.append(plat_name)
            elif c_status == "PENDING":
                has_pending = True
        else:
            social_account_status[plat_name] = {
                "connected": False,
                "status": "NOT_CONNECTED",
                "platform_account_id": None,
                "username": None
            }

    # Also inspect embedded profile_doc["social_accounts"]
    social_accounts = profile_doc.get("social_accounts") or {}
    for p, info in social_accounts.items():
        if isinstance(info, dict):
            if info.get("verified") or info.get("connected"):
                connected_platforms.append(p)
                has_verified = True
                if p in social_account_status:
                    social_account_status[p]["connected"] = True
                    social_account_status[p]["status"] = "VERIFIED"
            elif info.get("status") == "pending":
                has_pending = True

    connected_platforms = list(set(connected_platforms))
    verification_status = "VERIFIED" if has_verified else ("PENDING" if has_pending else "UNVERIFIED")

    full_name = profile_doc.get("full_name") or profile_doc.get("fullName") or user_doc.get("name") or user_doc.get("fullName") or ""
    username = profile_doc.get("username") or user_doc.get("username") or ""
    if username and isinstance(username, str):
        username = username.lstrip("@")
    profile_image = profile_doc.get("profile_image") or profile_doc.get("profileImageUrl") or user_doc.get("profileImageUrl") or user_doc.get("image") or ""
    bio = profile_doc.get("bio") or ""
    primary_niche = profile_doc.get("primary_niche") or profile_doc.get("category") or "Boutique and Fashion"
    location = profile_doc.get("location") or "India"
    gender = profile_doc.get("gender") or ""

    profile_summary = CreatorProfileSummary(
        user_id=user_id,
        full_name=full_name,
        username=username,
        profile_image=profile_image,
        bio=bio,
        primary_niche=primary_niche,
        location=location,
        gender=gender,
        verification_status=verification_status,
        social_accounts=social_accounts,
        connected_platforms=connected_platforms
    )

    profile_completion = calculate_profile_completion(profile_doc)

    # 2. Active deals & collaborations from database
    collabs_cursor = db["collaborations"].find({
        "influencer_id": user_id,
        "status": {"$in": ["active", "in_progress", "accepted", "pending", "IN_PROGRESS", "ACCEPTED", "PENDING_REVIEW"]}
    }).sort("created_at", -1)
    collab_docs = await collabs_cursor.to_list(length=50)

    active_deals: List[DealSummary] = []
    for c in collab_docs:
        camp_title = "Business Collaboration"
        camp_id = c.get("campaign_id")
        if camp_id and ObjectId.is_valid(camp_id):
            camp = await db["campaigns"].find_one({"_id": ObjectId(camp_id)})
            if camp:
                camp_title = camp.get("name") or camp.get("title") or camp_title

        biz_name = "Local Business Partner"
        biz_cat = "Small Business"
        biz_logo = ""
        biz_loc = "India"
        biz_id = c.get("business_id")
        if biz_id:
            biz = None
            if ObjectId.is_valid(biz_id):
                biz = await db["businesses"].find_one({"_id": ObjectId(biz_id)})
            if not biz:
                biz = await db["businesses"].find_one({"$or": [{"_id": biz_id}, {"id": biz_id}]})
            if biz:
                biz_name = biz.get("name") or biz.get("business_name") or biz_name
                biz_cat = normalize_business_category(biz.get("category"))
                biz_logo = biz.get("logo") or biz.get("logo_url") or ""
                biz_loc = biz.get("city") or biz.get("location") or biz_loc

        price = float(c.get("agreed_price") or 0.0)
        c_stat = canonical_collaboration_status(c.get("status"))
        active_deals.append(DealSummary(
            id=str(c["_id"]),
            title=camp_title,
            business_name=biz_name,
            business_category=biz_cat,
            business_logo=biz_logo,
            business_location=biz_loc,
            budget=price,
            budget_display=f"₹{price:,.0f}" if price > 0 else "Barter",
            status=c_stat,
            deadline=c["deadline"].isoformat() if c.get("deadline") else None,
            collaboration_type="Paid" if price > 0 else "Barter"
        ))

    # Collaboration counts
    active_collaborations_count = len(active_deals)
    apps_pending_count = await db["campaign_applications"].count_documents({
        "influencer_id": user_id,
        "status": {"$in": ["pending", "requested", "REQUESTED"]}
    })
    inbound_collabs_count = await db["influencer_campaigns"].count_documents({
        "influencer_id": user_id,
        "status": {"$in": ["pending", "requested", "REQUESTED"]}
    })
    collaboration_requests_count = apps_pending_count + inbound_collabs_count

    # 3. Available and recommended business opportunities
    # Check applications submitted by this creator to mark application status
    applied_apps = await db["campaign_applications"].find({"influencer_id": user_id}).to_list(100)
    applied_map = {str(a.get("campaign_id")): canonical_collaboration_status(a.get("status")) for a in applied_apps}

    brand_offers: List[BrandOfferSummary] = []

    # A. Real active campaigns in DB
    camp_cursor = db["campaigns"].find({"status": {"$in": ["active", "pending"]}}).sort("created_at", -1).limit(6)
    camp_docs = await camp_cursor.to_list(length=6)
    for c in camp_docs:
        cid = str(c["_id"])
        biz_name = "Local Business Partner"
        biz_cat = "Boutique and Fashion"
        biz_logo = ""
        biz_loc = "India"
        biz_id = c.get("business_id")
        if biz_id and ObjectId.is_valid(biz_id):
            biz = await db["businesses"].find_one({"_id": ObjectId(biz_id)})
            if biz:
                biz_name = biz.get("name") or biz.get("business_name") or biz_name
                biz_cat = normalize_business_category(biz.get("category"))
                biz_logo = biz.get("logo") or biz.get("logo_url") or ""
                biz_loc = biz.get("city") or biz.get("location") or biz_loc

        b_val = float(c.get("budget") or 0.0)
        brand_offers.append(BrandOfferSummary(
            id=cid,
            title=c.get("name") or c.get("title") or "Commercial Showcase",
            business_id=str(biz_id or ""),
            business_name=biz_name,
            business_category=biz_cat,
            business_logo=biz_logo,
            business_location=biz_loc,
            niche=c.get("niche") or [biz_cat],
            budget=b_val,
            budget_display=f"₹{b_val:,.0f}" if b_val > 0 else "Performance Based",
            platforms=c.get("platforms") or ["Instagram"],
            duration=c.get("duration", "14 Days"),
            deliverables=c.get("deliverables") or ["1 Dedicated Reel", "2 Stories"],
            collaboration_type=c.get("collaboration_type", "Paid"),
            is_applied=cid in applied_map,
            application_status=applied_map.get(cid)
        ))

    # B. Curated platform opportunities across all 9 small business categories
    for opp in PLATFORM_DEFAULT_OPPORTUNITIES:
        b_info = opp["business"]
        c_info = opp["campaign"]
        opp_id = c_info["id"]
        brand_offers.append(BrandOfferSummary(
            id=opp_id,
            title=c_info["title"],
            business_id=b_info["id"],
            business_name=b_info["name"],
            business_category=b_info["category"],
            business_logo=b_info["logo"],
            business_location=b_info["location"],
            niche=c_info["niche"],
            budget=float(c_info["budget"]),
            budget_display=c_info["budget_display"],
            platforms=c_info["platforms"],
            duration=c_info["duration"],
            deliverables=c_info["deliverables"],
            collaboration_type=c_info.get("collaboration_type", "Paid"),
            is_applied=opp_id in applied_map,
            application_status=applied_map.get(opp_id)
        ))

    # 4. Earnings from actual records
    pipeline = [
        {"$match": {"influencer_id": user_id, "status": {"$in": ["completed", "published", "approved", "COMPLETED"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$agreed_price"}}}
    ]
    earnings_res = await db["collaborations"].aggregate(pipeline).to_list(1)
    total_earnings = float(earnings_res[0]["total"]) if earnings_res else 0.0

    pending_pipeline = [
        {"$match": {"influencer_id": user_id, "status": "pending"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]
    pending_res = await db["influencer_earnings"].aggregate(pending_pipeline).to_list(1)
    pending_payout = float(pending_res[0]["total"]) if pending_res else 0.0

    completed_deals_count = await db["collaborations"].count_documents({
        "influencer_id": user_id,
        "status": {"$in": ["completed", "published", "approved", "COMPLETED"]}
    })

    earnings = EarningsSummary(
        total_earnings=total_earnings,
        pending_payout=pending_payout,
        completed_deals_count=completed_deals_count,
        currency="INR"
    )

    # 5. Performance metrics from actual database values
    total_apps_count = await db["campaign_applications"].count_documents({"influencer_id": user_id})
    acc_rate = round((completed_deals_count / total_apps_count * 100), 1) if total_apps_count > 0 else 0.0

    followers = profile_doc.get("followers") or profile_doc.get("follower_count") or 0
    engagement_rate = float(profile_doc.get("engagement_rate") or 0.0)

    metrics = PerformanceMetrics(
        total_reach=int(followers),
        engagement_rate=engagement_rate,
        completed_collaborations=completed_deals_count,
        active_collaborations=active_collaborations_count,
        acceptance_rate=acc_rate
    )

    # 6. Recent activity from actual database records (no fake events)
    recent_activity: List[RecentActivityItem] = []
    
    recent_apps = await db["campaign_applications"].find({"influencer_id": user_id}).sort("created_at", -1).limit(5).to_list(5)
    for a in recent_apps:
        recent_activity.append(RecentActivityItem(
            id=str(a["_id"]),
            activity_type="deal_applied",
            title="Applied for Collaboration",
            description=f"Status: {canonical_collaboration_status(a.get('status'))}. Proposed: ₹{a.get('proposed_price') or a.get('proposed_budget') or 0}",
            timestamp=a["created_at"].isoformat() if a.get("created_at") else now.isoformat(),
            meta={"application_id": str(a["_id"]), "status": canonical_collaboration_status(a.get("status"))}
        ))

    for c in collab_docs[:5]:
        recent_activity.append(RecentActivityItem(
            id=str(c["_id"]),
            activity_type="deal_accepted",
            title="Collaboration In Progress",
            description=f"Status: {canonical_collaboration_status(c.get('status'))}. Agreed: ₹{c.get('agreed_price', 0)}",
            timestamp=c["created_at"].isoformat() if c.get("created_at") else now.isoformat(),
            meta={"collaboration_id": str(c["_id"])}
        ))

    recent_activity.sort(key=lambda x: x.timestamp, reverse=True)

    # 7. Unread chat count
    unread_count = await ChatService.get_unread_message_count(user_id)

    data = InfluencerDashboardData(
        profile=profile_summary,
        verification_status=verification_status,
        social_account_status=social_account_status,
        profile_completion=profile_completion,
        active_collaborations_count=active_collaborations_count,
        collaboration_requests_count=collaboration_requests_count,
        earnings=earnings,
        recommended_business_opportunities=brand_offers,
        available_brand_offers=brand_offers,
        active_collaborations=active_deals,
        active_deals=active_deals,
        performance_metrics=metrics,
        recent_activity=recent_activity[:10],
        unread_chat_count=unread_count,
        unread_message_count=unread_count
    )

    return InfluencerDashboardResponse(success=True, data=data)


# =====================================================================
# 4. BUSINESS OPPORTUNITIES API
# =====================================================================

@router.get("/influencers/opportunities")
@router.get("/influencer/opportunities")
async def get_opportunities(
    page: int = Query(1, ge=1),
    limit: int = Query(6, ge=1, le=50),
    search: Optional[str] = Query(None, description="Search by business name, title, or keywords"),
    category: Optional[str] = Query(None, description="Filter by business category"),
    niche: Optional[str] = Query(None, description="Alias for category"),
    location: Optional[str] = Query(None, description="Filter by city or location"),
    city: Optional[str] = Query(None, description="Alias for location"),
    platform: Optional[str] = Query(None, description="Instagram, YouTube, LinkedIn, etc."),
    collaboration_type: Optional[str] = Query(None, description="Paid, Barter, Product Promotion"),
    min_budget: Optional[float] = Query(None, ge=0),
    max_budget: Optional[float] = Query(None, ge=0),
    sort_by: Optional[str] = Query("latest", description="latest, recommended, budget_high, budget_low"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Search and filter active small business opportunities.
    Supports business name search, category, location, compensation range, and sorting.
    """
    user_id = str(current_user.id)
    db = get_database()

    # Effective filters
    eff_cat = (category or niche or "").strip()
    eff_loc = (location or city or "").strip()

    # 1. Fetch user's applied opportunity IDs
    applied_apps = await db["campaign_applications"].find({"influencer_id": user_id}).to_list(200)
    applied_map = {str(a.get("campaign_id")): canonical_collaboration_status(a.get("status")) for a in applied_apps}

    # 2. Gather active DB campaigns and opportunities
    db_items: List[Dict[str, Any]] = []

    # Query influencer_campaigns
    cursor = db["influencer_campaigns"].find({
        "$or": [{"influencer_id": user_id}, {"status": {"$in": ["pending", "active"]}}]
    }).sort("created_at", -1)
    db_camps = await cursor.to_list(50)

    for c in db_camps:
        cid = str(c["_id"])
        b_id = c.get("business_id")
        business_name = "Local Business Partner"
        business_cat = "Boutique and Fashion"
        business_loc = "India"
        business_logo = "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80"
        business_desc = "Verified Business Partner on DhandaGrow"

        if b_id and ObjectId.is_valid(b_id):
            b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
            if b_doc:
                business_name = b_doc.get("name") or b_doc.get("business_name") or business_name
                business_cat = normalize_business_category(b_doc.get("category"))
                business_loc = b_doc.get("city") or b_doc.get("location") or business_loc
                business_logo = b_doc.get("logo") or b_doc.get("logo_url") or business_logo
                business_desc = b_doc.get("description") or business_desc

        b_val = float(c.get("budget", 5000))
        db_items.append({
            "id": cid,
            "business": {
                "id": str(b_id or "biz-default"),
                "name": business_name,
                "logo": business_logo,
                "category": business_cat,
                "location": business_loc,
                "description": business_desc
            },
            "campaign": {
                "id": cid,
                "title": c.get("name") or c.get("title") or f"Commercial Showcase with {business_name}",
                "description": c.get("ai_pitch_message") or "Collaborate on sponsored reels, stories, and authentic reviews.",
                "niche": [business_cat],
                "platforms": ["Instagram"],
                "collaboration_type": "Paid",
                "budget": b_val,
                "budget_display": f"₹{int(b_val):,}",
                "duration": "14 Days",
                "target_audience": "Engaged local and online shoppers",
                "deliverables": c.get("deliverables") or ["1 Dedicated Reel", "2 Stories"],
                "status": "active",
                "created_at": c.get("created_at", datetime.now(timezone.utc)).isoformat() if isinstance(c.get("created_at"), datetime) else str(c.get("created_at"))
            },
            "is_applied": cid in applied_map,
            "application_status": applied_map.get(cid)
        })

    # Combine DB items with curated platform small business opportunities
    all_items = list(db_items)
    existing_ids = {item["id"] for item in all_items}
    for def_opp in PLATFORM_DEFAULT_OPPORTUNITIES:
        if def_opp["id"] not in existing_ids:
            item_copy = dict(def_opp)
            item_copy["is_applied"] = def_opp["id"] in applied_map
            item_copy["application_status"] = applied_map.get(def_opp["id"])
            all_items.append(item_copy)

    # 3. Filtering
    filtered = []
    for item in all_items:
        camp = item["campaign"]
        biz = item["business"]

        # Search by business name, title or description
        if search:
            s = search.lower().strip()
            text_corpus = f"{biz['name']} {camp['title']} {camp.get('description', '')} {biz.get('category', '')} {biz.get('description', '')}".lower()
            if s not in text_corpus:
                continue

        # Category / niche filter
        if eff_cat and eff_cat.lower() != "all":
            norm_filter_cat = normalize_business_category(eff_cat).lower()
            biz_norm_cat = normalize_business_category(biz.get("category", "")).lower()
            camp_niches = [normalize_business_category(n).lower() for n in camp.get("niche", [])]
            if norm_filter_cat != biz_norm_cat and norm_filter_cat not in camp_niches:
                continue

        # Location / city filter
        if eff_loc and eff_loc.lower() != "all":
            loc_s = eff_loc.lower().strip()
            biz_loc_str = str(biz.get("location", "")).lower()
            if loc_s not in biz_loc_str:
                continue

        # Platform filter
        if platform and platform.lower() != "all":
            plat_lower = platform.lower()
            camp_plats = [p.lower() for p in camp.get("platforms", [])]
            if plat_lower not in camp_plats:
                continue

        # Collaboration type
        if collaboration_type and collaboration_type.lower() != "all":
            ct = collaboration_type.lower()
            item_ct = str(camp.get("collaboration_type", "")).lower()
            if ct not in item_ct:
                continue

        # Budget range
        budget_num = float(camp.get("budget", 0))
        if min_budget is not None and budget_num < min_budget:
            continue
        if max_budget is not None and budget_num > max_budget:
            continue

        filtered.append(item)

    # 4. Sorting
    if sort_by == "budget_high":
        filtered.sort(key=lambda x: float(x["campaign"].get("budget", 0)), reverse=True)
    elif sort_by == "budget_low":
        filtered.sort(key=lambda x: float(x["campaign"].get("budget", 0)))
    elif sort_by == "recommended":
        # Prioritize opportunities matching creator's primary niche
        creator_profile = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}
        c_niche = normalize_business_category(creator_profile.get("primary_niche") or creator_profile.get("category")).lower()
        filtered.sort(key=lambda x: 1 if normalize_business_category(x["business"].get("category", "")).lower() == c_niche else 2)
    else:  # latest
        filtered.sort(key=lambda x: str(x["campaign"].get("created_at", "")), reverse=True)

    # 5. Pagination
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

    applied = await db["campaign_applications"].find_one({
        "influencer_id": user_id,
        "campaign_id": opportunity_id
    })
    app_status = canonical_collaboration_status(applied.get("status")) if applied else None

    # Search in curated default opportunities
    for opp in PLATFORM_DEFAULT_OPPORTUNITIES:
        if opp["id"] == opportunity_id or opp["campaign"]["id"] == opportunity_id:
            res = dict(opp)
            res["is_applied"] = applied is not None
            res["application_status"] = app_status
            return {"success": True, "data": res}

    # Search in DB
    if ObjectId.is_valid(opportunity_id):
        camp = await db["influencer_campaigns"].find_one({"_id": ObjectId(opportunity_id)})
        if not camp:
            camp = await db["campaigns"].find_one({"_id": ObjectId(opportunity_id)})
        if camp:
            b_id = camp.get("business_id")
            business_name = "Local Business Partner"
            business_cat = "Boutique and Fashion"
            business_loc = "India"
            business_logo = "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=200&q=80"
            business_desc = "Verified Business Partner on DhandaGrow"

            if b_id and ObjectId.is_valid(b_id):
                b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
                if b_doc:
                    business_name = b_doc.get("name") or b_doc.get("business_name") or business_name
                    business_cat = normalize_business_category(b_doc.get("category"))
                    business_loc = b_doc.get("city") or b_doc.get("location") or business_loc
                    business_logo = b_doc.get("logo") or b_doc.get("logo_url") or business_logo
                    business_desc = b_doc.get("description") or business_desc

            b_val = float(camp.get("budget", 5000))
            item = {
                "id": str(camp["_id"]),
                "business": {
                    "id": str(b_id or "biz-default"),
                    "name": business_name,
                    "logo": business_logo,
                    "category": business_cat,
                    "location": business_loc,
                    "description": business_desc
                },
                "campaign": {
                    "id": str(camp["_id"]),
                    "title": camp.get("name") or camp.get("title") or "Commercial Showcase",
                    "description": camp.get("ai_pitch_message") or "Collaborate on sponsored reels and stories.",
                    "niche": [business_cat],
                    "platforms": camp.get("platforms") or ["Instagram"],
                    "collaboration_type": camp.get("collaboration_type", "Paid"),
                    "budget": b_val,
                    "budget_display": f"₹{int(b_val):,}",
                    "duration": camp.get("duration", "14 Days"),
                    "target_audience": "Urban engaged audiences",
                    "deliverables": camp.get("deliverables") or ["1 Reel", "2 Stories"],
                    "status": "active",
                    "created_at": str(camp.get("created_at"))
                },
                "is_applied": applied is not None,
                "application_status": app_status
            }
            return {"success": True, "data": item}

    raise HTTPException(status_code=404, detail="Opportunity not found")


# =====================================================================
# 5. COLLABORATION APIS (REQUESTED, ACCEPTED, IN_PROGRESS, COMPLETED, etc.)
# =====================================================================

@router.get("/influencer/collaborations")
@router.get("/influencers/collaborations")
@router.get("/influencer/my-collaborations")
@router.get("/influencers/my-collaborations")
async def list_collaborations(
    status: Optional[str] = Query(None, description="REQUESTED, ACCEPTED, IN_PROGRESS, PENDING_REVIEW, COMPLETED, REJECTED, CANCELLED"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List all collaborations for the authenticated creator.
    Supports status filtering and attaches full business & campaign context.
    """
    user_id = str(current_user.id)
    db = get_database()

    # 1. Fetch from collaborations collection
    collabs = await db["collaborations"].find({"influencer_id": user_id}).sort("created_at", -1).to_list(100)

    # 2. Fetch pending or rejected applications not yet converted to active collaborations
    apps = await db["campaign_applications"].find({"influencer_id": user_id}).sort("created_at", -1).to_list(100)

    # Track seen collaboration IDs to avoid duplicate rows
    seen_ids = set()
    results = []

    for c in collabs:
        cid = str(c["_id"])
        seen_ids.add(cid)
        c_status = canonical_collaboration_status(c.get("status"))

        # Filter by status if specified
        if status and status.upper() != "ALL" and c_status != status.upper():
            continue

        # Attach business details
        b_id = c.get("business_id")
        business_info = {
            "id": str(b_id or ""),
            "name": "Local Business Partner",
            "category": "Small Business",
            "location": "India",
            "logo": ""
        }
        if b_id and ObjectId.is_valid(b_id):
            b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
            if b_doc:
                business_info["name"] = b_doc.get("name") or b_doc.get("business_name") or business_info["name"]
                business_info["category"] = normalize_business_category(b_doc.get("category"))
                business_info["location"] = b_doc.get("city") or b_doc.get("location") or business_info["location"]
                business_info["logo"] = b_doc.get("logo") or b_doc.get("logo_url") or ""

        price = float(c.get("agreed_price") or 0.0)
        results.append({
            "id": cid,
            "collaboration_id": cid,
            "campaign_id": str(c.get("campaign_id") or ""),
            "business_id": str(b_id or ""),
            "business": business_info,
            "business_name": business_info["name"],
            "business_category": business_info["category"],
            "business_location": business_info["location"],
            "business_logo": business_info["logo"],
            "campaign_title": c.get("campaign_name") or "Business Collaboration",
            "agreed_price": price,
            "budget": price,
            "budget_display": f"₹{price:,.0f}" if price > 0 else "Barter",
            "deliverables": c.get("deliverables") or ["1 Reel"],
            "status": c_status,
            "canonical_status": c_status,
            "deadline": c["deadline"].isoformat() if c.get("deadline") else None,
            "created_at": c["created_at"].isoformat() if c.get("created_at") else datetime.now(timezone.utc).isoformat()
        })

    # Add standalone applications (REQUESTED or REJECTED)
    for a in apps:
        aid = str(a["_id"])
        c_status = canonical_collaboration_status(a.get("status"))

        if status and status.upper() != "ALL" and c_status != status.upper():
            continue

        camp_id = str(a.get("campaign_id") or "")
        # Avoid duplicate if already represented in collabs
        if any(r["campaign_id"] == camp_id for r in results):
            continue

        b_id = a.get("business_id")
        business_info = {
            "id": str(b_id or ""),
            "name": "Local Business Partner",
            "category": "Small Business",
            "location": "India",
            "logo": ""
        }
        if b_id and ObjectId.is_valid(b_id):
            b_doc = await db["businesses"].find_one({"_id": ObjectId(b_id)})
            if b_doc:
                business_info["name"] = b_doc.get("name") or b_doc.get("business_name") or business_info["name"]
                business_info["category"] = normalize_business_category(b_doc.get("category"))
                business_info["location"] = b_doc.get("city") or b_doc.get("location") or business_info["location"]
                business_info["logo"] = b_doc.get("logo") or b_doc.get("logo_url") or ""

        b_budget = float(a.get("proposed_budget") or a.get("proposed_price") or 0.0)
        results.append({
            "id": aid,
            "collaboration_id": aid,
            "campaign_id": camp_id,
            "business_id": str(b_id or ""),
            "business": business_info,
            "business_name": business_info["name"],
            "business_category": business_info["category"],
            "business_location": business_info["location"],
            "business_logo": business_info["logo"],
            "campaign_title": "Collaboration Proposal",
            "agreed_price": b_budget,
            "budget": b_budget,
            "budget_display": f"₹{b_budget:,.0f}" if b_budget > 0 else "Negotiable",
            "deliverables": a.get("deliverables") or ["1 Reel"],
            "status": c_status,
            "canonical_status": c_status,
            "deadline": None,
            "created_at": a["created_at"].isoformat() if a.get("created_at") else datetime.now(timezone.utc).isoformat()
        })

    return {"success": True, "data": results}


@router.get("/influencer/collaborations/{collaboration_id}")
@router.get("/influencers/collaborations/{collaboration_id}")
async def get_collaboration_by_id(
    collaboration_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Retrieve single collaboration by ID.
    Strictly validates business and creator permissions.
    """
    user_id = str(current_user.id)
    db = get_database()

    doc = None
    is_collab = False

    if ObjectId.is_valid(collaboration_id):
        doc = await db["collaborations"].find_one({"_id": ObjectId(collaboration_id)})
        if doc:
            is_collab = True
        else:
            doc = await db["campaign_applications"].find_one({"_id": ObjectId(collaboration_id)})

    if not doc:
        doc = await db["campaign_applications"].find_one({"$or": [{"_id": collaboration_id}, {"id": collaboration_id}]})

    if not doc:
        raise HTTPException(status_code=404, detail="Collaboration not found")

    # Security check: Creator must be the influencer OR user must own the business
    influencer_id = str(doc.get("influencer_id") or "")
    business_id = str(doc.get("business_id") or "")

    is_creator = (influencer_id == user_id)
    is_biz_owner = False
    if business_id and ObjectId.is_valid(business_id):
        biz_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        if biz_doc and str(biz_doc.get("owner_id")) == user_id:
            is_biz_owner = True

    if not is_creator and not is_biz_owner:
        raise HTTPException(status_code=403, detail="You are not authorized to view this collaboration")

    # Attach business info
    business_info = {
        "id": business_id,
        "name": "Local Business Partner",
        "category": "Small Business",
        "location": "India",
        "logo": ""
    }
    if business_id and ObjectId.is_valid(business_id):
        b_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        if b_doc:
            business_info["name"] = b_doc.get("name") or b_doc.get("business_name") or business_info["name"]
            business_info["category"] = normalize_business_category(b_doc.get("category"))
            business_info["location"] = b_doc.get("city") or b_doc.get("location") or business_info["location"]
            business_info["logo"] = b_doc.get("logo") or b_doc.get("logo_url") or ""

    c_status = canonical_collaboration_status(doc.get("status"))
    price = float(doc.get("agreed_price") or doc.get("proposed_budget") or 0.0)

    result = {
        "id": str(doc["_id"]),
        "collaboration_id": str(doc["_id"]),
        "campaign_id": str(doc.get("campaign_id") or ""),
        "business_id": business_id,
        "business": business_info,
        "business_name": business_info["name"],
        "business_category": business_info["category"],
        "business_location": business_info["location"],
        "business_logo": business_info["logo"],
        "influencer_id": influencer_id,
        "agreed_price": price,
        "budget_display": f"₹{price:,.0f}" if price > 0 else "Barter",
        "deliverables": doc.get("deliverables") or ["1 Reel"],
        "status": c_status,
        "canonical_status": c_status,
        "deadline": doc["deadline"].isoformat() if doc.get("deadline") else None,
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else datetime.now(timezone.utc).isoformat()
    }
    return {"success": True, "data": result}


@router.post("/influencer/collaborations/{collaboration_id}/apply")
@router.post("/influencers/collaborations/{collaboration_id}/apply")
@router.post("/influencer/opportunities/{collaboration_id}/apply")
@router.post("/influencers/opportunities/{collaboration_id}/apply")
async def apply_for_collaboration(
    collaboration_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Apply for a business collaboration or opportunity.
    Enforces uniqueness (prevents duplicate applications).
    Sets initial status to REQUESTED.
    """
    user_id = str(current_user.id)
    db = get_database()
    now = datetime.now(timezone.utc)

    # 1. Prevent duplicate active applications
    existing = await db["campaign_applications"].find_one({
        "campaign_id": collaboration_id,
        "influencer_id": user_id
    })
    if existing:
        curr_status = canonical_collaboration_status(existing.get("status"))
        if curr_status in ["REQUESTED", "ACCEPTED", "IN_PROGRESS", "COMPLETED"]:
            raise HTTPException(
                status_code=400,
                detail=f"Already applied to this collaboration opportunity (Status: {curr_status})"
            )

    pitch_message = (payload.get("pitch_message") or payload.get("message") or "").strip()
    if not pitch_message or len(pitch_message) < 5:
        raise HTTPException(status_code=400, detail="Please provide a pitch message (at least 5 characters).")

    # 2. Resolve creator profile
    inf_profile = await db["influencer_profiles"].find_one({"user_id": user_id}) or {}
    inf_name = inf_profile.get("fullName") or inf_profile.get("full_name") or getattr(current_user, "name", "Creator")
    inf_username = inf_profile.get("username") or ""

    # 3. Resolve business ID from campaign if available
    business_id = payload.get("business_id")
    if not business_id and ObjectId.is_valid(collaboration_id):
        camp = await db["campaigns"].find_one({"_id": ObjectId(collaboration_id)})
        if not camp:
            camp = await db["influencer_campaigns"].find_one({"_id": ObjectId(collaboration_id)})
        if camp:
            business_id = str(camp.get("business_id") or "")

    app_doc = {
        "campaign_id": collaboration_id,
        "influencer_id": user_id,
        "influencer_name": inf_name,
        "influencer_username": inf_username,
        "business_id": business_id or "biz-default",
        "pitch_message": pitch_message,
        "proposed_budget": payload.get("proposed_budget") or payload.get("proposed_price"),
        "deliverables": payload.get("deliverables") or ["1 Reel", "2 Stories"],
        "status": "REQUESTED",
        "canonical_status": "REQUESTED",
        "created_at": now,
        "updated_at": now
    }

    res = await db["campaign_applications"].insert_one(app_doc)
    app_id = str(res.inserted_id)

    # 4. Notify business via real-time WebSocket if business user is connected
    try:
        if business_id and ObjectId.is_valid(business_id):
            b_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
            if b_doc and b_doc.get("owner_id"):
                await chat_ws_manager.send_to_user(str(b_doc["owner_id"]), {
                    "event": "collaboration_requested",
                    "application_id": app_id,
                    "campaign_id": collaboration_id,
                    "influencer_name": inf_name,
                    "pitch_message": pitch_message
                })
    except Exception as e:
        pass

    return {
        "success": True,
        "message": "Collaboration application submitted successfully! Status set to REQUESTED.",
        "application_id": app_id,
        "status": "REQUESTED"
    }


# =====================================================================
# 6. PAYOUT ACCOUNT & PORTFOLIO
# =====================================================================

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
