from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.influencer_service import InfluencerService
from app.services.business_service import BusinessService

router = APIRouter(prefix="/influencers", tags=["Influencers"])

@router.get("/discover")
async def discover_influencers(current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    b_id = str(business.id) if business else None
    if not b_id:
        return {"success": False, "message": "No business profile found."}
        
    influencers = await InfluencerService.discover_influencers(b_id)
    return {"success": True, "data": influencers}

class InfluencerCreate(BaseModel):
    name: str
    platform: str
    niche: str
    followers_count: int
    engagement_rate: float
    contact_email: str

@router.post("/add")
async def add_influencer(req: InfluencerCreate, current_user = Depends(get_current_user)):
    try:
        inf = await InfluencerService.add_influencer(req.model_dump())
        return {"success": True, "data": inf}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{influencer_id}/generate-pitch")
async def generate_pitch(influencer_id: str, current_user = Depends(get_current_user)):
    try:
        business = await BusinessService.get_business_by_owner(str(current_user.id))
        b_id = str(business.id) if business else None
        if not b_id:
             raise Exception("No business profile found.")
        
        pitch = await InfluencerService.generate_pitch(b_id, influencer_id, str(current_user.id))
        return {"success": True, "pitch": pitch}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class CampaignCreate(BaseModel):
    influencer_id: str
    message: str
    budget: float = 0

@router.post("/campaigns")
async def create_campaign(req: CampaignCreate, current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=400, detail="No business profile found")
        
    campaign = await InfluencerService.create_campaign(str(business.id), req.influencer_id, req.message, req.budget)
    return {"success": True, "data": campaign}
    
@router.get("/campaigns")
async def get_campaigns(current_user = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        return {"success": True, "data": []}
        
    campaigns = await InfluencerService.get_campaigns(str(business.id))
    return {"success": True, "data": campaigns}
