from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.models.influencer_profile import InfluencerProfile
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter(prefix="/influencer/profile", tags=["Influencer Profile"])

@router.get("/me")
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

@router.put("/me")
async def update_my_profile(profile_data: dict, current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access this endpoint", "data": None}
        
    db = get_database()
    
    # Clean up data
    profile_data.pop("_id", None)
    profile_data.pop("id", None)
    profile_data["user_id"] = current_user.id
    profile_data["updated_at"] = datetime.now(timezone.utc)
    
    existing = await db["influencer_profiles"].find_one({"user_id": current_user.id})
    
    if existing:
        await db["influencer_profiles"].update_one(
            {"user_id": current_user.id},
            {"$set": profile_data}
        )
    else:
        profile_data["created_at"] = datetime.now(timezone.utc)
        await db["influencer_profiles"].insert_one(profile_data)
        
    updated = await db["influencer_profiles"].find_one({"user_id": current_user.id})
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

