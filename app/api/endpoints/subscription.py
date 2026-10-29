from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional, List
from app.core.security import get_current_user, get_current_user_optional
from app.core.database import get_database
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
from app.services.plan_onboarding_service import PlanOnboardingService
from app.services.payin_service import PayinService
from app.schemas.payment import (
    PaymentTransactionListResponse,
    TestPlanResetRequest,
    TestPlanResetResponse,
)
from app.schemas.billing_onboarding import PlanOnboardingStatusResponse
from app.core.billing_config import PLANS, BILLING_CYCLES, get_formatted_plans

router = APIRouter(
    prefix="/subscription",
    tags=["Subscription"]
)

class UpgradeRequest(BaseModel):
    plan_id: str
    billing_cycle: Optional[str] = "monthly"
    order_id: Optional[str] = None

@router.get("/onboarding-status", response_model=PlanOnboardingStatusResponse)
async def get_plan_onboarding_status(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns Step 3: Plan Selection and Activation onboarding status.
    Determines if the plan popup should open based on:
    1. Brand Kit completed (Step 1)
    2. At least one social media account connected (Step 2)
    3. No qualifying plan active (Step 3 incomplete)
    """
    return await PlanOnboardingService.get_plan_onboarding_status(db, current_user)

@router.get("/plans")
async def get_plans(
    current_user=Depends(get_current_user_optional),
    db=Depends(get_database)
):
    active_plan_id = "FREE"
    if current_user:
        user_id = str(current_user.get("id") or current_user.get("_id"))
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        active_plan_id = sub.get("plan_id", "FREE")

    enriched_plans = {}
    for k, v in PLANS.items():
        enriched = dict(v)
        if enriched.get("gst_applicable"):
            gst = enriched.get("gst_amount", int(enriched["price"] * 0.18))
            enriched["gst_amount"] = gst
            enriched["total_price"] = enriched.get("total_price", enriched["price"] + gst)
        else:
            enriched["gst_amount"] = 0
            enriched["total_price"] = enriched["price"]
        enriched_plans[k] = enriched

    formatted = get_formatted_plans(active_plan_id)
    return {
        "success": True,
        "data": enriched_plans,
        "plans_list": formatted,
        "billing_cycles": BILLING_CYCLES
    }

@router.get("/available-plans")
async def get_available_plans_endpoint(
    current_user=Depends(get_current_user_optional),
    db=Depends(get_database)
):
    active_plan_id = "FREE"
    if current_user:
        user_id = str(current_user.get("id") or current_user.get("_id"))
        sub = await SubscriptionService.get_or_create_subscription(db, user_id)
        active_plan_id = sub.get("plan_id", "FREE")
    return {
        "success": True,
        "data": get_formatted_plans(active_plan_id),
        "billing_cycles": BILLING_CYCLES
    }

@router.get("/me")
async def get_my_subscription(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    user_id = str(current_user["id"])
    sub = await SubscriptionService.get_or_create_subscription(db, user_id)
    
    # Get current month usage
    from datetime import datetime, timezone
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = await db["usage"].find_one({"user_id": user_id, "month": current_month})
    
    if not usage:
        usage = {"posts_created": 0, "reels_created": 0}
        
    sub["usage"] = usage
    plan_id = sub.get("plan_id", "FREE")
    sub["plan_details"] = PLANS.get(plan_id) or (PLANS.get("GROWTH") if plan_id == "PRO" else PLANS.get("FREE"))
    
    # Check business plan onboarding completion and eligibility
    plan_status = await PlanOnboardingService.get_plan_onboarding_status(db, current_user)
    business = await db["businesses"].find_one({
        "$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}, {"user_id": str(user_id)}]
    })
    sub["plan_activation_completed"] = plan_status.plan_activation_completed
    sub["is_eligible"] = plan_status.is_eligible
    sub["should_show_modal"] = plan_status.should_show_modal
    sub["requires_plan_selection"] = plan_status.requires_plan_selection
    sub["is_plan_required"] = plan_status.is_plan_required
    sub["is_paid_plan"] = plan_status.is_paid_plan
    sub["current_plan"] = plan_id
    sub["subscription_status"] = sub.get("status", "inactive")

    # Exclude _id to avoid serialization issues
    if "_id" in sub:
        sub["id"] = str(sub.pop("_id"))
    if "_id" in sub["usage"]:
        del sub["usage"]["_id"]

    return {
        "success": True,
        "data": sub,
        "requires_plan_selection": plan_status.requires_plan_selection,
        "is_plan_required": plan_status.is_plan_required,
        "is_eligible": plan_status.is_eligible,
        "should_show_modal": plan_status.should_show_modal,
        "is_paid_plan": plan_status.is_paid_plan,
        "current_plan": plan_id,
        "subscription_status": sub.get("status", "inactive"),
    }


@router.post("/checkout")
async def checkout(
    request: UpgradeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    normalized = (request.plan_id or "").upper().strip()
    if normalized not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
        
    # Return checkout metadata
    return {
        "success": True,
        "message": "Proceed to payment",
        "plan_id": normalized,
        "billing_cycle": request.billing_cycle or "monthly"
    }

@router.post("/upgrade")
async def upgrade_subscription(
    request: UpgradeRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    normalized = (request.plan_id or "").upper().strip()
    user_id = str(current_user["id"])
    if normalized == "FREE":
        sub = await SubscriptionService.activate_free_plan(db, user_id)
        return {"success": True, "message": "Free plan activated successfully", "data": sub}

    if normalized not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    from app.services.payin_service import PayinService
    # For paid plans, require verified payment
    if not request.order_id:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment required. Please create and complete payment via /api/v1/payments/payin/create first."
        )

    tx = await db["payment_transactions"].find_one({"order_id": request.order_id, "user_id": user_id})
    if not tx:
        raise HTTPException(status_code=404, detail="Payment transaction not found")

    if tx.get("status") != "success":
        # Check provider status before deciding
        verify_res = await PayinService.verify_payment_with_provider(db, request.order_id)
        if not verify_res.get("verified"):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Payment not verified. Current status: {tx.get('status')}"
            )

    sub = await db["subscriptions"].find_one({"user_id": user_id})
    if sub and "_id" in sub:
        sub["id"] = str(sub.pop("_id"))
    return {"success": True, "message": f"Payment verified and upgraded to {normalized} successfully", "data": sub}

@router.get("/credits")
async def get_credits(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    sub = await SubscriptionService.get_or_create_subscription(db, str(current_user["id"]))
    return {"success": True, "credits_remaining": sub.get("credits_remaining", 0)}

@router.get("/credits/transactions")
async def get_credit_transactions(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    history = await CreditService.get_history(db, str(current_user["id"]))
    return {"success": True, "data": history}

@router.get("/credits/summary")
async def get_credit_summary_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    summary = await CreditService.get_credit_summary(db, str(current_user["id"]))
    return {"success": True, "data": summary}

@router.post("/activate-free")
@router.post("/select-free")
async def activate_free_plan_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Activates the ₹0 Free tier plan for the authenticated user.
    Records the free plan activation in subscription_history, grants 5 credits idempotently,
    and marks Step 3 plan onboarding as completed.
    """
    user_id = str(current_user["id"])
    sub = await SubscriptionService.activate_free_plan(db, user_id)
    return {
        "success": True,
        "message": "Free plan activated successfully",
        "data": sub
    }

@router.post("/skip")
async def skip_plan_selection_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Allows the user to skip the Step 3 plan selection modal.
    Prevents the modal from continuously reopening while keeping plan_activation_completed as is.
    """
    from datetime import datetime, timezone
    user_id = str(current_user["id"])
    now = datetime.now(timezone.utc)
    await db["businesses"].update_one(
        {"owner_id": user_id},
        {"$set": {"plan_selection_skipped": True, "plan_selection_skipped_at": now}},
        upsert=True
    )
    return {
        "success": True,
        "message": "Plan selection skipped successfully",
        "plan_selection_skipped": True
    }

@router.get("/billing-report")
@router.get("/billing/report")
async def get_billing_report_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns an auditable billing report for the authenticated user,
    including current subscription, free and paid plan history, payment transactions,
    and credit usage summary.
    """
    user_id = str(current_user["id"])
    report = await SubscriptionService.get_billing_report(db, user_id)
    return {
        "success": True,
        "data": report
    }

@router.get("/history")
@router.get("/billing/history")
async def get_subscription_history_endpoint(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns the subscription history (both free ₹0 activations and paid plans) for the authenticated user.
    """
    user_id = str(current_user["id"])
    history = await SubscriptionService.get_subscription_history(db, user_id)
    return {
        "success": True,
        "data": history
    }



@router.get("/transactions", response_model=PaymentTransactionListResponse)
async def get_subscription_transactions_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (success, pending, cancelled, failed)"),
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Returns user-scoped payment transactions history with pagination and date sorting.
    """
    user_id = str(current_user["id"])
    return await PayinService.get_user_transactions(db, user_id, page=page, limit=limit, status=status)

@router.post("/test-plan/reset", response_model=TestPlanResetResponse)
async def reset_subscription_test_plan_endpoint(
    request: Optional[TestPlanResetRequest] = None,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Safely resets a test user's ₹1 TEST_PLAN subscription back to FREE state.
    """
    caller_id = str(current_user.get("id") or current_user.get("_id"))
    caller_role = str(current_user.get("role", "")).lower()

    target_user_id = caller_id
    admin_override = False

    if request and request.target_user_id:
        if caller_role in ["admin", "administrator", "superuser"]:
            target_user_id = request.target_user_id.strip()
            admin_override = True
        elif request.target_user_id.strip() != caller_id:
            raise HTTPException(status_code=403, detail="Only administrators can reset test plans for other users.")

    result = await PayinService.reset_test_subscription(db, target_user_id, admin_override=admin_override)
    return TestPlanResetResponse(**result)
