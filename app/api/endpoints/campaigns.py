from fastapi import APIRouter, Depends, HTTPException
from typing import List

from app.core.security import get_current_user
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.services.campaign_service import CampaignService
from app.schemas.campaign import CampaignCreate, CampaignUpdate, CampaignResponse

router = APIRouter(
    prefix="/campaigns",
    tags=["Campaigns"]
)

async def get_current_business(current_user=Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        # Developer mode fallback: mock the business using the user's ID
        class MockBusiness:
            id = current_user.id
        return MockBusiness()
    return business

@router.post("", response_model=dict)
async def create_campaign(
    request: CampaignCreate,
    current_user=Depends(get_current_user),
    business=Depends(get_current_business)
):
    db = get_database()
    campaign_svc = CampaignService(db)
    
    saved_doc = await campaign_svc.create_campaign(
        user_id=str(current_user.id),
        business_id=str(business.id),
        payload=request.model_dump(exclude_unset=True)
    )
    
    return {"success": True, "data": saved_doc}

@router.get("", response_model=dict)
async def get_campaigns(
    current_user=Depends(get_current_user),
    business=Depends(get_current_business)
):
    db = get_database()
    campaign_svc = CampaignService(db)
    
    campaigns = await campaign_svc.get_campaigns(business_id=str(business.id))
    return {"success": True, "data": campaigns}

@router.get("/{campaign_id}", response_model=dict)
async def get_campaign(
    campaign_id: str,
    current_user=Depends(get_current_user),
    business=Depends(get_current_business)
):
    db = get_database()
    campaign_svc = CampaignService(db)
    
    campaign = await campaign_svc.get_campaign_by_id(campaign_id, str(business.id))
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    return {"success": True, "data": campaign}

@router.put("/{campaign_id}", response_model=dict)
async def update_campaign(
    campaign_id: str,
    request: CampaignUpdate,
    current_user=Depends(get_current_user),
    business=Depends(get_current_business)
):
    db = get_database()
    campaign_svc = CampaignService(db)
    
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return await get_campaign(campaign_id, current_user, business)
        
    updated_doc = await campaign_svc.update_campaign(campaign_id, str(business.id), updates)
    if not updated_doc:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    return {"success": True, "data": updated_doc}

@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    current_user=Depends(get_current_user),
    business=Depends(get_current_business)
):
    db = get_database()
    campaign_svc = CampaignService(db)
    
    success = await campaign_svc.delete_campaign(campaign_id, str(business.id))
    if not success:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    return {"success": True, "message": "Campaign deleted"}
