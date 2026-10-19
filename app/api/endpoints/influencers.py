from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
from app.core.database import get_database
from app.services.influencer_service import InfluencerService
from app.schemas.influencer import (
    InfluencerProfileUpdate,
    InfluencerProfileResponse,
    OpportunitiesResponse,
    DashboardSummaryResponse,
    ApplyOpportunityRequest,
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
