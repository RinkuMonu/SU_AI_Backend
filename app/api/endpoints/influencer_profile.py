from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.models.influencer_profile import InfluencerProfile
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter(tags=["Influencer Profile"])

@router.get("/influencer/profile/me")
@router.get("/influencer/me")
@router.get("/influencer/profile")
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access this endpoint", "data": None}
        
    db = get_database()
    profile_doc = await db["influencer_profiles"].find_one({"user_id": current_user.id})
    
    if not profile_doc:
        # Return empty shell
        return {"success": True, "data": None}
        
    profile_doc["id"] = str(profile_doc["_id"])
    profile_doc.pop("_id", None)
    return {"success": True, "data": profile_doc}

@router.put("/influencer/profile/me")
@router.post("/influencer/profile/me")
@router.put("/influencer/profile")
@router.post("/influencer/profile")
@router.put("/influencer/me")
@router.post("/influencer/me")
@router.put("/influencer")
@router.post("/influencer")
async def update_my_profile(profile_data: dict, current_user: CurrentUser = Depends(get_current_user)):
    user_id = str(getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None))
    role = getattr(current_user, "role", None) or (current_user.get("role") if isinstance(current_user, dict) else None)
    
    if role == "businessman":
        return {"success": False, "message": "Only influencers can access this endpoint", "data": None}
        
    db = get_database()
    now = datetime.now(timezone.utc)
    
    # 1. Fetch existing profile
    existing = await db["influencer_profiles"].find_one({"user_id": user_id})
    
    # 2. Extract legitimately supplied fields, avoiding overwriting existing data with None or empty
    clean_input = {}
    for k, v in profile_data.items():
        if k in ["_id", "id", "user_id", "created_at"]:
            continue
        if v is None:
            continue
        if isinstance(v, str) and not v.strip() and existing and existing.get(k):
            continue
        clean_input[k] = v

    # 3. Merge over existing document to preserve omitted fields
    merged = dict(existing) if existing else {
        "user_id": user_id,
        "created_at": now
    }
    merged.update(clean_input)
    merged["user_id"] = user_id
    merged["updated_at"] = now
    
    # Clean up location if it contains None/null
    loc = merged.get("location")
    if loc and any(bad in str(loc).lower() for bad in ["none", "null"]):
        merged["location"] = "India"
        
    # Clean leading @ from username
    if merged.get("username") and isinstance(merged["username"], str):
        merged["username"] = merged["username"].lstrip("@")
        
    # Populate user identity fallbacks from db["users"] if missing
    if not merged.get("fullName") or not merged.get("username"):
        from bson import ObjectId
        u = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
        if u:
            if not merged.get("fullName"):
                merged["fullName"] = u.get("name") or u.get("fullName")
            if not merged.get("username"):
                merged["username"] = (u.get("username") or (u.get("email", "").split("@")[0] if u.get("email") else "creator")).lstrip("@")

    # 4. Calculate profile completion percentage
    meaningful_fields = ["bio", "category", "location", "expectedPricePerPost", "languages", "profile_image", "instagram_url", "follower_count"]
    completed_count = 0
    for f in meaningful_fields:
        val = merged.get(f)
        if val is not None and val != "" and val != []:
            if f == "follower_count" and val == 0:
                pass
            else:
                completed_count += 1
    merged["profile_completion"] = int(round((completed_count / len(meaningful_fields)) * 100))

    # 5. Persist to MongoDB
    if existing:
        await db["influencer_profiles"].update_one(
            {"_id": existing["_id"]},
            {"$set": merged}
        )
        updated = await db["influencer_profiles"].find_one({"_id": existing["_id"]})
    else:
        res = await db["influencer_profiles"].insert_one(merged)
        updated = await db["influencer_profiles"].find_one({"_id": res.inserted_id})
        
    updated["id"] = str(updated["_id"])
    updated.pop("_id", None)
    
    return {"success": True, "data": updated}

@router.post("/me/portfolio")
async def add_portfolio_item(item: dict, current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access this endpoint", "data": None}
        
    db = get_database()
    
    item["created_at"] = datetime.now(timezone.utc)
    
    result = await db["influencer_profiles"].update_one(
        {"user_id": current_user.id},
        {"$push": {"portfolio": item}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=400, detail="Profile not found. Please setup profile first.")
        
    return {"success": True, "message": "Portfolio updated"}

