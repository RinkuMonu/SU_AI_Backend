from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from app.core.security import get_current_user, require_admin
from app.core.database import get_database
from app.services.marketplace_service import MarketplaceService
from app.services.payin_service import PayinService
from app.utils.response import serialize_mongo
from app.schemas.marketplace import (
    HiringRequestCreate,
    HiringRequestRespond,
    AgreementSignRequest,
    PaymentCreateOrderRequest,
    PaymentVerifyRequest,
    MarketplaceMessageCreate,
    DeliverablesSubmitRequest,
    DeliverablesReviewRequest,
    AdminDisputeResolveRequest
)

router = APIRouter(
    prefix="/marketplace",
    tags=["Influencer Marketplace"]
)

# -------------------------------------------------------------
# PHASE 1: INFLUENCER DISCOVERY
# -------------------------------------------------------------
@router.get("/discover", response_model=dict)
async def discover_influencers(
    search: Optional[str] = Query(None, description="Search by name, username, or bio"),
    platform: Optional[str] = Query(None, description="Instagram, YouTube, etc."),
    min_followers: Optional[int] = Query(None, ge=0, description="Minimum followers"),
    max_followers: Optional[int] = Query(None, ge=0, description="Maximum followers"),
    location: Optional[str] = Query(None, description="City, state, or country"),
    niche: Optional[str] = Query(None, description="Influencer category / niche"),
    min_engagement: Optional[float] = Query(None, ge=0, description="Minimum engagement rate %"),
    is_verified: Optional[bool] = Query(None, description="Verification status"),
    sort_by: Optional[str] = Query("followers_desc", description="followers_desc, followers_asc, engagement_desc, price_asc, price_desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(12, ge=1, le=50, description="Items per page"),
    db=Depends(get_database)
):
    """
    Search, filter, and paginate verified influencer profiles from MongoDB.
    Returns real database records with full statistics.
    """
    try:
        data = await MarketplaceService.discover_influencers(
            db=db,
            search=search,
            platform=platform,
            min_followers=min_followers,
            max_followers=max_followers,
            location=location,
            niche=niche,
            min_engagement=min_engagement,
            is_verified=is_verified,
            sort_by=sort_by,
            page=page,
            limit=limit
        )
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to discover influencers: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 4A: PLATFORM SERVICE FEE
# -------------------------------------------------------------
@router.get("/service-fee", response_model=dict)
async def get_platform_service_fee(
    db=Depends(get_database)
):
    """Retrieve dynamic platform hiring service fee."""
    try:
        fee_data = await MarketplaceService.get_service_fee(db)
        return {"success": True, "data": fee_data}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch service fee: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 2: HIRING REQUEST WORKFLOW
# -------------------------------------------------------------
@router.post("/hiring", response_model=dict)
async def create_hiring_request(
    payload: HiringRequestCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Create a new formal hiring request targeting an influencer."""
    try:
        created = await MarketplaceService.create_hiring_request(
            db=db,
            current_user=current_user,
            data=payload.model_dump()
        )
        return {
            "success": True,
            "message": "Hiring request sent successfully to the influencer",
            "data": serialize_mongo(created)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create hiring request: {str(e)}"
        )

@router.get("/hiring", response_model=dict)
async def get_my_hiring_requests(
    status: Optional[str] = Query(None, description="Filter by request status"),
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve all hiring requests where current user is either Hirer or Creator."""
    try:
        reqs = await MarketplaceService.get_hiring_requests(
            db=db,
            user_id=str(current_user.id),
            status_filter=status
        )
        return {"success": True, "data": reqs}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load hiring requests: {str(e)}"
        )

@router.get("/hiring/{request_id}", response_model=dict)
async def get_hiring_request_detail(
    request_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve specific hiring request with authorization validation."""
    try:
        req = await MarketplaceService.get_hiring_request_by_id(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": req}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch hiring request: {str(e)}"
        )

@router.put("/hiring/{request_id}/respond", response_model=dict)
async def respond_to_hiring_request(
    request_id: str,
    payload: HiringRequestRespond,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Influencer accepts or rejects the hiring proposal."""
    try:
        result = await MarketplaceService.respond_to_hiring_request(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            action=payload.action,
            note=payload.note
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to respond to hiring request: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 3: ELECTRONIC AGREEMENT
# -------------------------------------------------------------
@router.get("/hiring/{request_id}/agreement", response_model=dict)
async def get_hiring_agreement(
    request_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Fetch legal bilateral agreement document for this campaign."""
    try:
        agreement = await MarketplaceService.get_agreement(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": agreement}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load agreement: {str(e)}"
        )

@router.post("/hiring/{request_id}/sign-agreement", response_model=dict)
async def sign_hiring_agreement(
    request_id: str,
    payload: AgreementSignRequest,
    req_http: Request,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Submit electronic signature with timestamp and audit digest."""
    client_ip = req_http.client.host if req_http.client else "127.0.0.1"
    try:
        result = await MarketplaceService.sign_agreement(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            signer_name=payload.signer_name,
            declaration_accepted=payload.declaration_accepted,
            signer_title=payload.signer_title,
            ip_address=client_ip
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sign agreement: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 4: PAYMENT ORDER & VERIFICATION
# -------------------------------------------------------------
@router.post("/hiring/{request_id}/payment/create", response_model=dict)
async def create_hiring_payment_order(
    request_id: str,
    payload: Optional[PaymentCreateOrderRequest] = None,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Create payment order for platform service fee + campaign compensation."""
    try:
        order = await MarketplaceService.create_hiring_payment(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": order}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create payment order: {str(e)}"
        )

@router.post("/hiring/{request_id}/payment/verify", response_model=dict)
async def verify_hiring_payment_order(
    request_id: str,
    payload: PaymentVerifyRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Confirm payment receipt server-side and activate collaboration in_progress."""
    try:
        result = await MarketplaceService.verify_hiring_payment(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            order_id=payload.order_id,
            payment_id=payload.payment_id
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify payment: {str(e)}"
        )

# -------------------------------------------------------------
# ZAAKPAY INFLUENCER HIRING FEE (₹200)
# -------------------------------------------------------------
@router.post("/hiring/{request_id}/pay-hire-fee", response_model=dict)
async def pay_influencer_hire_fee(
    request_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Initiate ₹200 Influencer Hiring Platform Fee via Zaakpay / Finunique Payment Gateway.
    Cuts ₹200 fee upon clicking 'Hire Influencer'.
    """
    try:
        user_email = getattr(current_user, "email", "user@example.com")
        res = await PayinService.create_hire_influencer_payment(
            db=db,
            user_id=str(current_user.id),
            user_email=user_email,
            hiring_request_id=request_id,
            amount=200.0
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate ₹200 Zaakpay payment: {str(e)}"
        )

@router.post("/hiring/{request_id}/verify-hire-fee", response_model=dict)
async def verify_influencer_hire_fee(
    request_id: str,
    payload: PaymentVerifyRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Verify ₹200 payment and officially activate hiring request to creator."""
    try:
        res = await PayinService.verify_hire_payment(
            db=db,
            order_id=payload.order_id,
            payment_id=payload.payment_id
        )
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify hire payment: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 5: PRIVATE CHAT ROOM & MESSAGES
# -------------------------------------------------------------
@router.get("/hiring/{request_id}/chat", response_model=dict)
async def get_collaboration_chat(
    request_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Retrieve chat room info with prerequisite and authorization validation."""
    try:
        chat = await MarketplaceService.get_chat_room(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": chat}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load chat room: {str(e)}"
        )

@router.get("/hiring/{request_id}/messages", response_model=dict)
async def get_collaboration_messages(
    request_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Fetch message history for authorized participants."""
    try:
        msgs = await MarketplaceService.get_messages(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": msgs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load messages: {str(e)}"
        )

@router.post("/hiring/{request_id}/messages", response_model=dict)
async def send_collaboration_message(
    request_id: str,
    payload: MarketplaceMessageCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Post a message inside the private collaboration room."""
    try:
        msg = await MarketplaceService.send_message(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            current_user=current_user,
            message=payload.message,
            attachments=payload.attachments
        )
        return {"success": True, "data": msg}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 6: DELIVERABLES SUBMISSION & REVIEW
# -------------------------------------------------------------
@router.post("/hiring/{request_id}/submit-deliverables", response_model=dict)
async def submit_deliverables(
    request_id: str,
    payload: DeliverablesSubmitRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Influencer submits finished campaign deliverables."""
    try:
        result = await MarketplaceService.submit_deliverables(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            live_links=payload.live_links,
            attachments=payload.attachments,
            notes=payload.notes
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit deliverables: {str(e)}"
        )

@router.post("/hiring/{request_id}/review-deliverables", response_model=dict)
async def review_deliverables(
    request_id: str,
    payload: DeliverablesReviewRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Hirer reviews work: approve, request revision, or report dispute."""
    try:
        result = await MarketplaceService.review_deliverables(
            db=db,
            request_id=request_id,
            user_id=str(current_user.id),
            action=payload.action,
            review_notes=payload.review_notes,
            dispute_reason=payload.dispute_reason
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to review deliverables: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 7: INFLUENCER EARNINGS & PAYOUTS
# -------------------------------------------------------------
@router.get("/earnings", response_model=dict)
async def get_my_marketplace_earnings(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """Fetch completed payouts and settlement ledger for creator."""
    try:
        ledger = await MarketplaceService.get_influencer_earnings_ledger(
            db=db,
            user_id=str(current_user.id)
        )
        return {"success": True, "data": ledger}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load earnings ledger: {str(e)}"
        )

# -------------------------------------------------------------
# PHASE 8: ADMIN MARKETPLACE MANAGEMENT
# -------------------------------------------------------------
@router.get("/admin/overview", response_model=dict)
async def get_admin_marketplace_overview(
    admin=Depends(require_admin),
    db=Depends(get_database)
):
    """Admin dashboard stats for marketplace."""
    try:
        overview = await MarketplaceService.get_admin_marketplace_overview(db)
        return {"success": True, "data": overview}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load admin overview: {str(e)}"
        )

@router.get("/admin/hiring-requests", response_model=dict)
async def get_admin_all_hiring_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    admin=Depends(require_admin),
    db=Depends(get_database)
):
    """Admin view of all platform hiring requests."""
    try:
        reqs = await MarketplaceService.admin_get_all_requests(db, status=status)
        return {"success": True, "data": reqs}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load all hiring requests: {str(e)}"
        )

@router.post("/admin/hiring-requests/{request_id}/resolve-dispute", response_model=dict)
async def admin_resolve_dispute(
    request_id: str,
    payload: AdminDisputeResolveRequest,
    admin=Depends(require_admin),
    db=Depends(get_database)
):
    """Admin resolves a disputed collaboration."""
    try:
        result = await MarketplaceService.admin_resolve_dispute(
            db=db,
            request_id=request_id,
            action=payload.action,
            notes=payload.resolution_notes,
            admin_id=str(admin.id)
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve dispute: {str(e)}"
        )
