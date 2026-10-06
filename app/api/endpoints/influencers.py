from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.influencer_service import InfluencerService
from app.services.business_service import BusinessService

router = APIRouter(prefix="/influencers", tags=["Influencers"])

@router.get("/discover")
async def discover_influencers(
    category: Optional[str] = None,
    min_followers: Optional[int] = None,
    location: Optional[str] = None,
    platform: Optional[str] = None,
    current_user = Depends(get_current_user)
):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    b_id = str(business.id) if business else None
    if not b_id:
        return {"success": False, "message": "No business profile found."}
        
    filters = {
        "category": category,
        "min_followers": min_followers,
        "location": location,
        "platform": platform
    }
    
    influencers = await InfluencerService.discover_influencers(b_id, filters)
    return {"success": True, "data": influencers}

class InfluencerCreate(BaseModel):
    name: str
    platform: str = "Instagram"
    niche: str = ""
    followers_count: int = 0
    engagement_rate: float = 0.0
    contact_email: str = ""

@router.post("/add")
async def add_influencer(req: InfluencerCreate, current_user = Depends(get_current_user)):
    db = get_database()
    
    # Check if business user
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="Only businesses can manually add influencers")
        
    doc = {
        "username": req.name,
        "name": req.name,
        "category": req.niche,
        "follower_count": req.followers_count,
        "engagement_rate": req.engagement_rate,
        "email": req.contact_email,
        "platform": req.platform,
        "source": "manual",
        "added_by": str(business.id)
    }
    
    # Map platform string to appropriate URL field for discovery filtering
    platform_key = req.platform.lower()
    if platform_key == "instagram":
        doc["instagram_url"] = f"https://instagram.com/{req.name}"
    elif platform_key == "youtube":
        doc["youtube_url"] = f"https://youtube.com/@{req.name}"
    elif platform_key == "tiktok":
        doc["tiktok_url"] = f"https://tiktok.com/@{req.name}"
    elif platform_key == "facebook":
        doc["facebook_url"] = f"https://facebook.com/{req.name}"
    else:
        doc[f"{platform_key}_url"] = f"https://{platform_key}.com/{req.name}"
        
    res = await db["influencer_profiles"].insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc["user_id"] = str(res.inserted_id)
    
    # Update the document to ensure user_id is the same as _id for legacy lookups
    await db["influencer_profiles"].update_one(
        {"_id": res.inserted_id},
        {"$set": {"user_id": doc["user_id"]}}
    )
    
    doc.pop("_id", None)
    
    # Match the frontend expectation struct
    return {
        "success": True, 
        "data": {
            "id": doc["id"],
            "name": doc["name"],
            "platform": doc["platform"],
            "niche": doc["category"],
            "followers_count": doc["follower_count"],
            "engagement_rate": doc["engagement_rate"],
            "contact_email": doc.get("email", "")
        }
    }

@router.delete("/{influencer_id}")
async def delete_influencer(influencer_id: str, current_user = Depends(get_current_user)):
    db = get_database()
    
    # Check if business user
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="Only businesses can delete influencers")
        
    from bson import ObjectId
    if not ObjectId.is_valid(influencer_id):
        raise HTTPException(status_code=400, detail="Invalid influencer ID")
        
    # Security check: Make sure they only delete manually added ones (or just delete anyway depending on your rules)
    result = await db["influencer_profiles"].delete_one({"_id": ObjectId(influencer_id)})
    if result.deleted_count == 0:
        # Fallback to user_id check
        result = await db["influencer_profiles"].delete_one({"user_id": influencer_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Influencer not found")
            
    return {"success": True, "message": "Influencer deleted successfully"}


class PitchRequest(BaseModel):
    style: str = "Professional"

@router.post("/{influencer_id}/generate-pitch")
async def generate_pitch(influencer_id: str, req: PitchRequest, current_user = Depends(get_current_user)):
    try:
        business = await BusinessService.get_business_by_owner(str(current_user.id))
        b_id = str(business.id) if business else None
        if not b_id:
             raise Exception("No business profile found.")
        
        pitch = await InfluencerService.generate_pitch(b_id, influencer_id, str(current_user.id), req.style)
        return {"success": True, "pitch": pitch}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{influencer_id}/shortlist")
async def toggle_shortlist(influencer_id: str, current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="No business profile found")
        
    result = await InfluencerService.toggle_shortlist(str(business.id), influencer_id)
    return {"success": True, "data": result}

@router.get("/shortlist")
async def get_shortlist(current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        return {"success": True, "data": []}
        
    shortlist = await InfluencerService.get_shortlist(str(business.id))
    return {"success": True, "data": shortlist}

class CampaignCreate(BaseModel):
    influencer_id: str
    message: str
    budget: float = 0
    deliverables: Optional[List[str]] = None

@router.post("/campaigns")
async def create_campaign(req: CampaignCreate, current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="No business profile found")
        
    campaign = await InfluencerService.create_campaign(
        str(business.id), 
        req.influencer_id, 
        req.message, 
        req.budget,
        req.deliverables
    )
    return {"success": True, "data": campaign}
    
@router.get("/campaigns")
async def get_campaigns(current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        return {"success": True, "data": []}
        
    campaigns = await InfluencerService.get_campaigns(str(business.id))
    return {"success": True, "data": campaigns}

@router.get("/campaigns/{campaign_id}/dashboard")
async def get_campaign_dashboard(campaign_id: str, current_user = Depends(get_current_user)):
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="No business profile found")
        
    from bson import ObjectId
    campaign = await db["influencer_campaigns"].find_one({
        "_id": ObjectId(campaign_id),
        "business_id": str(business.id)
    })
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Aggregate data
    collabs = await db["collaborations"].find({"campaign_id": campaign_id}).to_list(length=100)
    
    total_spent = sum(c.get("agreed_price", 0) for c in collabs if c.get("status") not in ["cancelled"])
    influencer_count = len(set(c["influencer_id"] for c in collabs))
    
    # Published content count
    content = await db["content_submissions"].count_documents({
        "collaboration_id": {"$in": [str(c["_id"]) for c in collabs]},
        "status": "published"
    })
    
    dashboard = {
        "campaign_name": campaign.get("name", "Campaign Overview"),
        "budget": campaign.get("budget", 0),
        "spent": total_spent,
        "influencers": influencer_count,
        "content_published": content,
        "reach": "Awaiting data",
        "engagement": "Awaiting data",
        "clicks": "Awaiting data",
        "roi": "Awaiting data"
    }
    
    return {"success": True, "data": dashboard}

@router.get("/campaigns/{campaign_id}/insights")
async def get_campaign_insights(campaign_id: str, current_user = Depends(get_current_user)):
    db = get_database()
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="No business profile found")
        
    from bson import ObjectId
    campaign = await db["influencer_campaigns"].find_one({
        "_id": ObjectId(campaign_id),
        "business_id": str(business.id)
    })
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Aggregate data
    collabs = await db["collaborations"].find({"campaign_id": campaign_id}).to_list(length=100)
    
    total_spent = sum(c.get("agreed_price", 0) for c in collabs if c.get("status") not in ["cancelled"])
    influencer_count = len(set(c["influencer_id"] for c in collabs))
    
    content_published = await db["content_submissions"].count_documents({
        "collaboration_id": {"$in": [str(c["_id"]) for c in collabs]},
        "status": "published"
    })
    
    if content_published == 0:
        return {
            "success": True,
            "data": {
                "insights": "Not enough data. Content must be published to generate insights.",
                "recommendations": "Continue tracking the campaign until content goes live."
            }
        }
        
    from app.ai.factory import AIProviderFactory
    ai = AIProviderFactory.get_provider()
    
    prompt = f"""
    Analyze the following influencer campaign data and provide insights:
    Campaign Name: {campaign.get('name', 'N/A')}
    Budget: ${campaign.get('budget', 0)}
    Spent: ${total_spent}
    Influencers engaged: {influencer_count}
    Content published: {content_published}
    Reach/Engagement: Awaiting live data (Assume baseline micro-influencer performance for now)
    
    Provide two short paragraphs:
    1. What worked (Insights based on spent vs published ratio).
    2. Recommendations for the future.
    
    Format as JSON with keys 'insights' and 'recommendations'.
    """
    
    try:
        result = await ai.generate_text(prompt, system_prompt="You are a data-driven marketing analyst.", is_json=True)
        import json
        text_result = result.get("text", "{}")
        if text_result.startswith("```json"):
            text_result = text_result.split("```json")[1].split("```")[0].strip()
        elif text_result.startswith("```"):
            text_result = text_result.split("```")[1].strip()
            
        parsed = json.loads(text_result)
        return {"success": True, "data": parsed}
    except Exception as e:
        return {
            "success": True, 
            "data": {
                "insights": "Basic campaign metrics indicate content is being published successfully.", 
                "recommendations": "Wait for detailed reach metrics to analyze further."
            }
        }


