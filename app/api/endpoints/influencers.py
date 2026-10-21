from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.core.database import get_database
from app.services.influencer_service import InfluencerService
from app.services.marketplace_service import MarketplaceService
from app.utils.response import serialize_mongo
from app.schemas.influencer import (
    InfluencerProfileUpdate,
    InfluencerProfileResponse,
    OpportunitiesResponse,
    DashboardSummaryResponse,
    ApplyOpportunityRequest,
    GeneratePitchRequest,
    PayoutAccountRequest,
    CRMCampaignCreateRequest,
    ApplicationStatusUpdateRequest
)

router = APIRouter(
    prefix="/influencers",
    tags=["Influencer Dashboard & Collaborations"]
)

@router.get("/me", response_model=dict)
async def get_my_influencer_profile(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Fetch current authenticated influencer profile with completion and social connection details."""
    try:
        profile = await InfluencerService.get_influencer_profile(db, str(current_user.id))
        return {"success": True, "data": profile}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile: {str(e)}"
        )

@router.put("/me", response_model=dict)
async def update_my_influencer_profile(
    payload: InfluencerProfileUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Update authenticated influencer profile details."""
    try:
        updated = await InfluencerService.update_influencer_profile(
            db,
            str(current_user.id),
            payload.model_dump(exclude_unset=True)
        )
        return {"success": True, "data": updated, "message": "Profile updated successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update profile: {str(e)}"
        )

@router.get("/dashboard/summary", response_model=dict)
async def get_dashboard_summary(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve verified summary metrics for the authenticated influencer dashboard."""
    try:
        summary = await InfluencerService.get_dashboard_summary(db, str(current_user.id))
        return {"success": True, "data": summary}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate dashboard summary: {str(e)}"
        )

@router.get("/opportunities", response_model=dict)
async def get_collaboration_opportunities(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by brand name or campaign keywords"),
    niche: Optional[str] = Query(None, description="Influencer niche / category"),
    platform: Optional[str] = Query(None, description="Social platform e.g. Instagram, YouTube"),
    location: Optional[str] = Query(None, description="Target location"),
    collaboration_type: Optional[str] = Query(None, description="Paid, Barter, Product Promotion"),
    min_budget: Optional[float] = Query(None, ge=0, description="Minimum compensation budget"),
    max_budget: Optional[float] = Query(None, ge=0, description="Maximum compensation budget"),
    status: Optional[str] = Query("active", description="Campaign status"),
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Retrieve business-generated collaboration opportunities available for influencers.
    Supports search, multi-attribute filtering, and pagination.
    """
    filters = {
        "search": search,
        "niche": niche,
        "platform": platform,
        "location": location,
        "collaboration_type": collaboration_type,
        "min_budget": min_budget,
        "max_budget": max_budget,
        "status": status,
    }
    try:
        data = await InfluencerService.get_opportunities(
            db=db,
            user_id=str(current_user.id),
            filters=filters,
            page=page,
            limit=limit
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load opportunities: {str(e)}"
        )

@router.get("/opportunities/{opportunity_id}", response_model=dict)
async def get_opportunity_details(
    opportunity_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve full details for a single collaboration opportunity."""
    try:
        opp = await InfluencerService.get_opportunity_by_id(db, opportunity_id, str(current_user.id))
        if not opp:
            raise HTTPException(status_code=404, detail="Collaboration opportunity not found")
        return {"success": True, "data": opp}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch opportunity: {str(e)}"
        )

@router.post("/opportunities/{opportunity_id}/apply", response_model=dict)
async def apply_for_opportunity(
    opportunity_id: str,
    payload: ApplyOpportunityRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Submit a collaboration proposal to a business campaign."""
    try:
        result = await InfluencerService.apply_for_opportunity(
            db=db,
            user_id=str(current_user.id),
            opportunity_id=opportunity_id,
            pitch_data=payload.model_dump()
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit proposal: {str(e)}"
        )

@router.get("/my-collaborations", response_model=dict)
async def get_my_collaborations(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve all collaborations and applications submitted by current influencer."""
    try:
        collabs = await InfluencerService.get_my_collaborations(db, str(current_user.id))
        return {"success": True, "data": collabs}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load collaborations: {str(e)}"
        )

@router.get("/discover", response_model=dict)
async def discover_influencers(
    search: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    min_followers: Optional[int] = Query(None),
    max_followers: Optional[int] = Query(None),
    location: Optional[str] = Query(None),
    niche: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    min_engagement: Optional[float] = Query(None),
    is_verified: Optional[bool] = Query(None),
    sort_by: Optional[str] = Query("followers_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    db=Depends(get_database)
):
    """Retrieve verified influencer directory from real database."""
    effective_niche = niche or category
    data = await MarketplaceService.discover_influencers(
        db=db,
        search=search,
        platform=platform,
        min_followers=min_followers,
        max_followers=max_followers,
        location=location,
        niche=effective_niche,
        min_engagement=min_engagement,
        is_verified=is_verified,
        sort_by=sort_by,
        page=page,
        limit=limit
    )
    return {"success": True, "data": data.get("items", []), "pagination": data.get("pagination")}

# -------------------------------------------------------------
# AI PITCH GENERATOR
# -------------------------------------------------------------
@router.post("/{influencer_id}/generate-pitch", response_model=dict)
async def generate_ai_pitch(
    influencer_id: str,
    payload: Optional[GeneratePitchRequest] = None,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Generate an AI-powered personalized pitch using Gemini for collaborating with this creator."""
    try:
        style = payload.style if payload else "professional"
        result = await InfluencerService.generate_ai_pitch(
            db=db,
            influencer_id=influencer_id,
            user_id=str(current_user.id),
            style=style
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate pitch: {str(e)}"
        )

# -------------------------------------------------------------
# SHORTLIST MANAGEMENT
# -------------------------------------------------------------
@router.post("/{influencer_id}/shortlist", response_model=dict)
async def toggle_shortlist(
    influencer_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Toggle bookmark / shortlist status for an influencer."""
    try:
        res = await InfluencerService.toggle_shortlist(db, str(current_user.id), influencer_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update shortlist: {str(e)}"
        )

@router.get("/shortlist", response_model=dict)
async def get_my_shortlist(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve all shortlisted influencers for authenticated brand user."""
    try:
        data = await InfluencerService.get_shortlist(db, str(current_user.id))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load shortlist: {str(e)}"
        )

# -------------------------------------------------------------
# INFLUENCER CRM CAMPAIGNS
# -------------------------------------------------------------
@router.post("/campaigns", response_model=dict)
async def create_crm_campaign(
    payload: CRMCampaignCreateRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Create an influencer CRM outreach campaign."""
    try:
        created = await InfluencerService.create_crm_campaign(
            db=db,
            user_id=str(current_user.id),
            data=payload.model_dump()
        )
        return {"success": True, "data": serialize_mongo(created), "message": "Campaign outreach created"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create CRM campaign: {str(e)}"
        )

@router.get("/campaigns", response_model=dict)
async def get_crm_campaigns(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve all influencer CRM outreach campaigns for brand."""
    try:
        items = await InfluencerService.get_crm_campaigns(db, str(current_user.id))
        return {"success": True, "data": items}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load CRM campaigns: {str(e)}"
        )

@router.get("/campaigns/{campaign_id}/dashboard", response_model=dict)
async def get_crm_campaign_dashboard(
    campaign_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve performance dashboard for a specific CRM collaboration."""
    try:
        data = await InfluencerService.get_crm_dashboard(db, campaign_id, str(current_user.id))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load campaign dashboard: {str(e)}"
        )

@router.get("/campaigns/{campaign_id}/insights", response_model=dict)
async def get_crm_campaign_insights(
    campaign_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve AI-powered recommendations and insights for collaboration."""
    try:
        data = await InfluencerService.get_crm_insights(db, campaign_id, str(current_user.id))
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load campaign insights: {str(e)}"
        )

# -------------------------------------------------------------
# BUSINESS COLLABORATION APPLICATIONS
# -------------------------------------------------------------
@router.get("/business/collaborations/applications", response_model=dict)
async def get_business_applications(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Fetch all proposals submitted by creators to this business."""
    try:
        apps = await InfluencerService.get_business_applications(db, str(current_user.id))
        return {"success": True, "data": apps}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load applications: {str(e)}"
        )

@router.put("/business/collaborations/applications/{app_id}/status", response_model=dict)
async def update_business_application_status(
    app_id: str,
    payload: ApplicationStatusUpdateRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Brand approves or rejects an influencer's campaign application."""
    try:
        res = await InfluencerService.update_application_status(
            db=db,
            business_user_id=str(current_user.id),
            app_id=app_id,
            new_status=payload.status
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update application status: {str(e)}"
        )

# -------------------------------------------------------------
# INFLUENCER PAYOUT ACCOUNT (BANK & UPI)
# -------------------------------------------------------------
@router.get("/me/payout-account", response_model=dict)
async def get_my_payout_account(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve current influencer payout account details."""
    try:
        res = await InfluencerService.get_payout_account(db, str(current_user.id))
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch payout account: {str(e)}"
        )

@router.post("/me/payout-account", response_model=dict)
async def save_my_payout_account(
    payload: PayoutAccountRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Save or update verified bank account and UPI VPA for creator payouts."""
    try:
        res = await InfluencerService.save_payout_account(
            db=db,
            user_id=str(current_user.id),
            payout_data=payload.model_dump()
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save payout account: {str(e)}"
        )

