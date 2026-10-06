from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from bson import ObjectId
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/influencer/marketplace", tags=["Influencer Marketplace"])

@router.get("/campaigns")
async def get_marketplace_campaigns(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    
    # Influencers can see campaigns targeted at them, plus all open 'pending' campaigns in the marketplace
    cursor = db["influencer_campaigns"].find({
        "$or": [
            {"influencer_id": str(current_user.id)},
            {"status": "pending"}
        ]
    }).sort("created_at", -1)
    campaigns = await cursor.to_list(length=100)
    
    results = []
    for c in campaigns:
        c["id"] = str(c.pop("_id"))
        
        # Attach business info
        business = await db["businesses"].find_one({"_id": ObjectId(c["business_id"])})
        if business:
            c["business_name"] = business.get("name", "Unknown Business")
            c["business_category"] = business.get("category", "")
        else:
            c["business_name"] = "Unknown Business"
        
        results.append(c)
        
    return {"success": True, "data": results}

class ApplicationPayload(BaseModel):
    message: str
    proposed_price: Optional[float] = None

@router.post("/campaigns/{campaign_id}/apply")
async def apply_for_campaign(
    campaign_id: str,
    payload: ApplicationPayload,
    current_user: CurrentUser = Depends(get_current_user)
):
    db = get_database()
    
    if ObjectId.is_valid(campaign_id):
        campaign = await db["influencer_campaigns"].find_one({"_id": ObjectId(campaign_id)})
    else:
        # Check both _id and id for string identifiers (mock data fallback)
        campaign = await db["influencer_campaigns"].find_one({"$or": [{"_id": campaign_id}, {"id": campaign_id}]})
        
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Check if already applied
    existing = await db["campaign_applications"].find_one({
        "campaign_id": campaign_id,
        "influencer_id": str(current_user.id)
    })
    
    if existing:
        raise HTTPException(status_code=400, detail="Already applied to this campaign")
        
    app_doc = {
        "campaign_id": campaign_id,
        "influencer_id": str(current_user.id),
        "business_id": campaign["business_id"],
        "message": payload.message,
        "proposed_price": payload.proposed_price,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    await db["campaign_applications"].insert_one(app_doc)
    
    # Also update the campaign status to show the influencer responded
    query = {"_id": campaign["_id"]}
    await db["influencer_campaigns"].update_one(
        query,
        {"$set": {"status": "applied", "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"success": True, "message": "Successfully applied for campaign"}

@router.get("/applications")
async def get_my_applications(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    
    cursor = db["campaign_applications"].find({"influencer_id": str(current_user.id)}).sort("created_at", -1)
    apps = await cursor.to_list(length=100)
    
    results = []
    for app in apps:
        app["id"] = str(app.pop("_id"))
        
        # Attach campaign info
        camp = await db["influencer_campaigns"].find_one({"_id": ObjectId(app["campaign_id"])})
        if camp:
            app["campaign_name"] = camp.get("name", "Campaign Invitation")
            app["budget"] = camp.get("budget", 0)
            
            # Attach business info
            business = await db["businesses"].find_one({"_id": ObjectId(camp["business_id"])})
            if business:
                app["business_name"] = business.get("name", "Unknown Business")
            
        results.append(app)
        
    return {"success": True, "data": results}
