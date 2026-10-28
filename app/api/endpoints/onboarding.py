from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Query
from fastapi.responses import RedirectResponse, Response
from typing import Dict, Any, Optional, List
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.core.categories import get_all_categories, get_subcategories, search_categories
from app.schemas.google_maps_onboarding import (
    GoogleMapsSearchRequest,
    GoogleMapsUrlResolveRequest,
    GoogleMapsPlaceItem,
    GoogleMapsSearchResponse,
    GoogleMapsResolveResponse,
    SelectGoogleMapsBusinessRequest,
    GoogleMapsWebsiteRequest,
    GoogleMapsCategoryRequest,
    GoogleMapsProfileRequest,
    GoogleMapsPhotoItem,
    GoogleMapsPhotosResponse,
    SelectGoogleMapsPhotosRequest,
    GoogleMapsOnboardingState,
    GoogleMapsOnboardingCompleteResponse,
)
from app.services.google_maps_onboarding_service import GoogleMapsOnboardingService
from app.schemas.platform_onboarding import (
    SavePlatformsRequest,
    PlatformOnboardingState,
    PlatformCatalogResponse,
    PlatformWebsiteSubmissionRequest,
    PlatformWebsiteSubmissionResponse,
    PlatformUrlAnalysisRequest,
    PlatformUrlAnalysisResponse,
)
from app.schemas.first_post import (
    FirstPostSourceImagesResponse,
    FirstPostImageUploadResponse,
    FirstPostGenerateRequest,
    FirstPostJobResponse,
    FirstContentChoiceRequest,
    FirstContentChoiceResponse,
)
from app.services.first_post_service import FirstPostService
from app.services.platform_onboarding_service import PlatformOnboardingService
from app.services.subscription_service import SubscriptionService
from app.services.onboarding_service import OnboardingService
from app.schemas.onboarding import (
    OnlinePresenceRequest,
    OnlinePresenceResponse,
    VALID_ONLINE_PRESENCE_OPTIONS,
    BusinessServicesSelectionRequest,
    BusinessServicesSelectionResponse,
    BusinessServicesCatalogResponse,
    SUPPORTED_BUSINESS_SERVICES,
)
from datetime import datetime, timezone
from bson import ObjectId

router = APIRouter()


from app.services.auth_service import AuthService
from app.services.brand_service import BrandService
from app.services.social_connectivity_service import SocialConnectivityService
from app.services.plan_onboarding_service import PlanOnboardingService
from app.schemas.website_analysis import (
    WebsiteAnalysisCreateRequest,
    WebsiteAnalysisJobResponse,
    WebsiteAnalysisStatusResponse,
    ApplyWebsiteAnalysisResponse,
    BusinessDetails,
    BrandPreferences,
    WebsitePhotoItem,
    WebsitePhotosResponse,
    SaveWebsitePhotosRequest,
    CompleteWebsiteOnboardingProfile,
    CompleteWebsiteOnboardingResponse
)
from app.services.website_analysis_service import WebsiteAnalysisService

@router.get("/status", response_model=Dict[str, Any])
async def get_onboarding_status(current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))

    # 1. Check business profile & Brand Kit (Step 1)
    business = await BusinessService.get_business_by_owner(uid)
    business_doc = await db["businesses"].find_one({"owner_id": uid})
    brand_status = await BrandService.get_onboarding_status(db, current_user)
    
    brand_kit_completed = brand_status.brand_kit_completed
    brand_kit_status_str = brand_status.brand_kit_status
    brand_kit_pct = brand_status.completion_percentage
    is_brand_dismissed = bool(
        getattr(brand_status, "brand_kit_dismissed", False) or
        (brand_status.brand_kit and brand_status.brand_kit.get("brand_kit_dismissed", False)) or
        (business_doc and business_doc.get("brand_kit_dismissed", False))
    )

    online_presence = (
        (business_doc.get("online_presence") if business_doc else None) or
        current_user.get("online_presence")
    )
    is_brand_kit_applicable = (online_presence == "no_online_presence") or (not online_presence)

    # Legacy business profile flag
    if not is_brand_kit_applicable:
        # Website, google_maps, marketplace_seller, wholesale_b2b do not require Brand Kit completion
        business_completed = True
    else:
        business_completed = brand_kit_completed or (brand_kit_pct > 0)
        if not business_completed and business:
            name = getattr(business, "businessName", None) or getattr(business, "name", None) or ""
            name = str(name).strip()
            if name and name != "My Business":
                business_completed = True

    # 2. Social Media Connectivity (Step 2)
    social_status = await SocialConnectivityService.get_social_onboarding_status(db, current_user)
    is_social_completed = social_status.social_connectivity_completed
    is_social_skipped = bool(
        (business_doc and business_doc.get("social_connectivity_skipped", False)) or
        current_user.get("social_connectivity_skipped", False)
    )
    
    connected_platforms = [p for p, info in social_status.platforms.items() if info.connected]
    # Also check user doc access tokens for fallback
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    if not user_doc:
        user_doc = await db["pending_users"].find_one({"_id": ObjectId(uid)})
    if user_doc:
        if user_doc.get("instagram_access_token") and "instagram" not in connected_platforms:
            connected_platforms.append("instagram")
        if user_doc.get("facebook_access_token") and "facebook" not in connected_platforms:
            connected_platforms.append("facebook")
    if connected_platforms:
        is_social_completed = True

    # 3. Subscription Plan (Step 3)
    plan_status = await PlanOnboardingService.get_plan_onboarding_status(db, current_user)
    sub = await SubscriptionService.get_or_create_subscription(db, uid)
    is_plan_completed = plan_status.plan_activation_completed
    is_plan_skipped = bool(
        (business_doc and business_doc.get("plan_selection_skipped", False)) or
        current_user.get("plan_selection_skipped", False)
    )

    # Determine recommended next action and modal
    current_modal = None
    if is_brand_kit_applicable and brand_status.should_show_modal:
        current_modal = "brand_kit"
        next_action = "Save your Brand Kit branding details"
    elif social_status.should_show_modal:
        current_modal = "social_connectivity"
        next_action = "Connect at least one social media account, or skip to continue"
    elif plan_status.should_show_modal:
        current_modal = "subscription_plan"
        next_action = "Select or activate your subscription plan"
    else:
        current_modal = None
        next_action = "Onboarding completed. Explore your AI workspace"

    # Overall completion percentage
    if not is_brand_kit_applicable:
        step1_weight = 40.0
    else:
        step1_weight = 40.0 * (brand_kit_pct / 100.0) if brand_kit_pct > 0 else (40.0 if is_brand_dismissed else 0.0)
    step2_weight = 30.0 if (is_social_completed or is_social_skipped) else 0.0
    step3_weight = 30.0 if (is_plan_completed or is_plan_skipped) else 0.0
    overall_pct = int(round(step1_weight + step2_weight + step3_weight))

    onboarding_step = user_doc.get("onboarding_step", 1) if user_doc else 1
    if business_completed and onboarding_step == 1:
        onboarding_step = 2
    if (is_social_completed or is_social_skipped) and onboarding_step == 2:
        onboarding_step = 3

    is_overall_completed = bool(
        user_doc.get("onboardingCompleted", False) or
        user_doc.get("onboarding_completed_at") or
        (business_completed and (is_social_completed or is_social_skipped) and (is_plan_completed or is_plan_skipped))
    )

    onboarding_state = OnboardingService.determine_state(user_doc or {}, business_doc)
    if is_overall_completed:
        onboarding_state["onboarding_completed"] = True
        onboarding_state["onboarding_status"] = "completed"
        onboarding_state["can_access_dashboard"] = True
        onboarding_state["requires_onboarding"] = False
        onboarding_state["next_step"] = "dashboard"
        onboarding_state["onboarding_route"] = "/dashboard/business"

    return {
        # Legacy compatibility keys
        "onboarding_completed": is_overall_completed,
        "onboardingCompleted": is_overall_completed,
        "is_completed": is_overall_completed,
        "is_pending": current_user.get("is_pending", False),
        "business_profile_completed": business_completed,
        "social_connection_completed": is_social_completed,
        "connected_platforms": connected_platforms,
        "onboarding_step": onboarding_step,
        "subscription_status": sub.get("status", "free"),
        "selected_plan_id": sub.get("plan_id", "FREE"),
        "onboarding_completed_at": user_doc.get("onboarding_completed_at") if user_doc else None,

        # State & Presence Management
        "onboarding_status": onboarding_state["onboarding_status"],
        "online_presence": onboarding_state.get("online_presence"),
        "business_type": onboarding_state.get("business_type"),
        "selected_services": onboarding_state.get("selected_services", []),
        "selectedServices": onboarding_state.get("selectedServices", []),
        "can_access_dashboard": onboarding_state["can_access_dashboard"],
        "requires_onboarding": onboarding_state["requires_onboarding"],
        "next_step": onboarding_state["next_step"],
        "onboarding_route": onboarding_state["onboarding_route"],
        "role": onboarding_state.get("role") or current_user.get("role"),

        # Three-step persistent status structure
        "overall_completion_percentage": overall_pct,
        "next_recommended_action": next_action,
        "current_modal_to_show": current_modal,
        "steps": {
            "step_1_brand_kit": {
                "status": "not_applicable" if not is_brand_kit_applicable else ("completed" if brand_kit_completed else ("in_progress" if brand_kit_pct > 0 else "not_started")),
                "is_completed": brand_kit_completed,
                "is_dismissed": is_brand_dismissed,
                "completion_percentage": brand_kit_pct,
                "completed_sections": brand_status.completed_sections,
                "pending_sections": brand_status.pending_sections,
                "should_show_modal": brand_status.should_show_modal if is_brand_kit_applicable else False,
                "is_applicable": is_brand_kit_applicable
            },
            "step_2_social_connectivity": {
                "status": "completed" if is_social_completed else ("skipped" if is_social_skipped else "pending"),
                "is_completed": is_social_completed,
                "is_skipped": is_social_skipped,
                "connected_count": len(connected_platforms),
                "connected_platforms": connected_platforms,
                "should_show_modal": social_status.should_show_modal
            },
            "step_3_subscription_plan": {
                "status": "completed" if is_plan_completed else ("skipped" if is_plan_skipped else "pending"),
                "is_completed": is_plan_completed,
                "is_skipped": is_plan_skipped,
                "is_eligible": plan_status.is_eligible,
                "active_plan": plan_status.active_plan.dict() if plan_status.active_plan else None,
                "should_show_modal": plan_status.should_show_modal
            }
        }
    }


@router.patch("/progress", response_model=Dict[str, Any])
async def update_onboarding_progress(payload: Dict[str, Any], current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id"))
    now = datetime.now(timezone.utc)

    allowed_fields = {
        "onboarding_step",
        "business_profile_completed",
        "social_connection_completed",
        "brand_kit_dismissed",
        "social_connectivity_skipped",
        "social_skipped",
        "plan_selection_skipped",
        "plan_skipped",
        "online_presence",
        "business_type",
        "selected_services",
        "selectedServices",
        "onboarding_status",
        "google_maps_url",
        "website_url",
        "website"
    }
    update_data = {k: v for k, v in payload.items() if k in allowed_fields}

    # Normalize skipped keys
    if "social_skipped" in update_data:
        update_data["social_connectivity_skipped"] = update_data.pop("social_skipped")
    if "plan_skipped" in update_data:
        update_data["plan_selection_skipped"] = update_data.pop("plan_skipped")

    # Normalize selected_services if passed
    if "selected_services" in update_data or "selectedServices" in update_data:
        raw_srv = update_data.get("selected_services") if "selected_services" in update_data else update_data.get("selectedServices")
        norm_srv_ids, srv_items = OnboardingService.validate_and_normalize_services(raw_srv)
        update_data["selected_services"] = norm_srv_ids
        update_data["selectedServices"] = norm_srv_ids

    if "online_presence" in update_data:
        presence = OnboardingService.normalize_online_presence(update_data["online_presence"])
        update_data["online_presence"] = presence
        if "business_type" not in update_data or not update_data["business_type"]:
            update_data["business_type"] = presence
        update_data["onboarding_status"] = "in_progress"
        c_step = update_data.get("onboarding_step")
        if not c_step or c_step <= 1:
            update_data["onboarding_step"] = 2

    if update_data:
        # Also update business doc for persistent onboarding state
        business_updates = {}
        if "social_connectivity_skipped" in update_data:
            business_updates["social_connectivity_skipped"] = update_data["social_connectivity_skipped"]
            business_updates["social_connectivity_skipped_at"] = now
        if "plan_selection_skipped" in update_data:
            business_updates["plan_selection_skipped"] = update_data["plan_selection_skipped"]
            business_updates["plan_selection_skipped_at"] = now
        if "brand_kit_dismissed" in update_data:
            business_updates["brand_kit_dismissed"] = update_data["brand_kit_dismissed"]
            business_updates["brand_kit_dismissed_at"] = now
        if "online_presence" in update_data:
            business_updates["online_presence"] = update_data["online_presence"]
        if "business_type" in update_data:
            business_updates["business_type"] = update_data["business_type"]
        if "selected_services" in update_data:
            business_updates["selected_services"] = update_data["selected_services"]
            business_updates["selectedServices"] = update_data["selectedServices"]
        if "google_maps_url" in update_data:
            business_updates["google_maps_url"] = update_data["google_maps_url"]
        if "website" in update_data:
            business_updates["website"] = update_data["website"]
        if "website_url" in update_data:
            business_updates["website"] = update_data["website_url"]

        if business_updates:
            business_updates["updated_at"] = now
            await db["businesses"].update_one(
                {"owner_id": uid},
                {"$set": business_updates},
                upsert=True
            )

        if update_data.get("social_connection_completed") or update_data.get("business_profile_completed"):
            update_data["onboarding_completed_at"] = now.isoformat()
            update_data["onboardingCompleted"] = True
            update_data["onboarding_status"] = "completed"
            await AuthService.commit_pending_user(uid, update_data)
        else:
            coll = db["pending_users"] if current_user.get("is_pending") else db["users"]
            await coll.update_one(
                {"_id": ObjectId(uid)},
                {"$set": update_data}
            )

    return {"success": True, "message": "Onboarding progress updated"}


@router.post("/online-presence", response_model=OnlinePresenceResponse)
@router.put("/online-presence", response_model=OnlinePresenceResponse)
async def set_online_presence(payload: OnlinePresenceRequest, current_user=Depends(get_current_user)):
    """
    Validates and persists the business online presence selection for the authenticated user.
    Advances the user to Step 2 (Brand Kit) and marks onboarding_status as 'in_progress'.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    result = await OnboardingService.save_online_presence(db, uid, payload.model_dump())
    return OnlinePresenceResponse(**result)


@router.get("/online-presence")
async def get_online_presence(current_user=Depends(get_current_user)):
    """
    Returns the currently selected business online presence and onboarding position.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)}) or await db["pending_users"].find_one({"_id": ObjectId(uid)}) or {}
    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]}) or {}
    state = OnboardingService.determine_state(user_doc, bus_doc)
    return {
        "success": True,
        "online_presence": state.get("online_presence"),
        "business_type": state.get("business_type"),
        "selected_services": state.get("selected_services", []),
        "selectedServices": state.get("selectedServices", []),
        "onboarding_step": state.get("onboarding_step", 1),
        "onboarding_status": state.get("onboarding_status", "not_started"),
        "next_step": state.get("next_step"),
        "can_access_dashboard": state.get("can_access_dashboard", False),
        "data": state
    }


@router.post("/services", response_model=BusinessServicesSelectionResponse)
@router.put("/services", response_model=BusinessServicesSelectionResponse)
async def save_business_services(
    payload: BusinessServicesSelectionRequest,
    current_user=Depends(get_current_user)
):
    """
    Saves the selected business services for the authenticated user and business.
    Validates each service ID against the supported catalog, deduplicates safely,
    and returns consistent response structure.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    result = await OnboardingService.save_selected_services(db, uid, payload.selected_services)
    return BusinessServicesSelectionResponse(**result)


@router.get("/services", response_model=BusinessServicesSelectionResponse)
async def get_business_services(current_user=Depends(get_current_user)):
    """
    Retrieves the authenticated user's saved business service selections.
    Enables frontend to restore selections across browser refresh or login sessions.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    result = await OnboardingService.get_selected_services(db, uid)
    return BusinessServicesSelectionResponse(**result)


@router.get("/services/catalog", response_model=BusinessServicesCatalogResponse)
async def get_business_services_catalog():
    """
    Returns the supported catalog of selectable business services.
    """
    result = OnboardingService.get_services_catalog()
    return BusinessServicesCatalogResponse(**result)


@router.post("/complete", response_model=Dict[str, Any])
async def complete_onboarding(payload: Dict[str, Any] = None, current_user=Depends(get_current_user)):
    """Explicitly finalize onboarding and commit user from pending_users to users collection."""
    uid = str(current_user.get("id"))
    extra_data = payload or {}
    now = datetime.now(timezone.utc)
    extra_data["onboardingCompleted"] = True
    extra_data["onboarding_completed_at"] = now.isoformat()
    extra_data["onboarding_status"] = "completed"
    user_doc = await AuthService.commit_pending_user(uid, extra_data)
    if not user_doc:
        raise HTTPException(status_code=404, detail="Failed to finalize onboarding user")
        
    user_doc["id"] = str(user_doc["_id"])
    del user_doc["_id"]
    return {
        "success": True,
        "message": "Onboarding completed successfully. Account is now active in database.",
        "data": user_doc
    }


@router.post("/website-analysis", response_model=WebsiteAnalysisJobResponse, status_code=status.HTTP_201_CREATED)
async def create_website_analysis_job(
    payload: WebsiteAnalysisCreateRequest,
    current_user=Depends(get_current_user)
):
    """
    Submits a website URL and onboarding type for analysis.
    Validates and normalizes the URL, checks SSRF safety, creates a background analysis job,
    and returns a unique job_id.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.create_analysis_job(db, uid, payload)


@router.get("/website-analysis/latest", response_model=WebsiteAnalysisStatusResponse)
@router.get("/website-analysis", response_model=WebsiteAnalysisStatusResponse)
async def get_latest_website_analysis(current_user=Depends(get_current_user)):
    """
    Retrieves the most recent website analysis job for the authenticated user.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    latest = await WebsiteAnalysisService.get_latest_job(db, uid)
    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No website analysis jobs found for this account."
        )
    return latest


@router.get("/website-analysis/{job_id}", response_model=WebsiteAnalysisStatusResponse)
async def get_website_analysis_status(
    job_id: str,
    current_user=Depends(get_current_user)
):
    """
    Polls the real-time processing status, progress, step statuses, and extracted results
    for a website analysis job.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.get_job_status(db, job_id, uid)


@router.post("/website-analysis/{job_id}/apply", response_model=ApplyWebsiteAnalysisResponse)
async def apply_website_analysis(
    job_id: str,
    current_user=Depends(get_current_user)
):
    """
    Explicitly applies the analyzed Brand Voice, Colors, Category, and Photos to the user's
    Brand Kit and business profile.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.apply_analysis_to_profile(db, job_id, uid)


# -----------------------------------------------------------------------------
# Dynamic Website Onboarding Flow (Screens 1 to 6)
# -----------------------------------------------------------------------------

@router.get("/business-profile", response_model=CompleteWebsiteOnboardingProfile)
@router.get("/website-analysis/profile", response_model=CompleteWebsiteOnboardingProfile)
async def get_website_business_profile(current_user=Depends(get_current_user)):
    """
    Retrieves the complete extracted profile (Business Details + Brand Preferences + Discovered Photos)
    for the authenticated user's website onboarding session.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.get_complete_profile(db, uid)


@router.put("/business-details", response_model=CompleteWebsiteOnboardingProfile)
@router.put("/website-analysis/business-details", response_model=CompleteWebsiteOnboardingProfile)
async def update_website_business_details(
    payload: BusinessDetails,
    current_user=Depends(get_current_user)
):
    """
    Saves confirmed / edited business details from Screen 1-3 ("Is this your business?")
    and advances onboarding to Brand Preferences (Step 2).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.update_business_details(db, uid, payload)


@router.put("/brand-preferences", response_model=CompleteWebsiteOnboardingProfile)
@router.put("/website-analysis/brand-preferences", response_model=CompleteWebsiteOnboardingProfile)
async def update_website_brand_preferences(
    payload: BrandPreferences,
    current_user=Depends(get_current_user)
):
    """
    Saves confirmed / edited brand preferences from Screen 4-5 ("What's your business like?")
    and advances onboarding to Website Photo Selection (Step 3).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.update_brand_preferences(db, uid, payload)


@router.get("/website-photos", response_model=WebsitePhotosResponse)
@router.get("/website-analysis/photos", response_model=WebsitePhotosResponse)
async def get_website_photos(current_user=Depends(get_current_user)):
    """
    Returns discovered images from the scraped website, along with current selection state.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.get_website_photos(db, uid)


@router.post("/website-photos", response_model=WebsitePhotosResponse)
@router.post("/website-analysis/photos", response_model=WebsitePhotosResponse)
async def save_website_photos(
    payload: SaveWebsitePhotosRequest,
    current_user=Depends(get_current_user)
):
    """
    Persists chosen photo selections (maximum 10) for brand assets.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.save_selected_photos(db, uid, payload.selected_photo_urls)


@router.post("/website-photos/upload", response_model=WebsitePhotoItem)
@router.post("/website-analysis/photos/upload", response_model=WebsitePhotoItem)
async def upload_website_photo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """
    Uploads a user-supplied business image, validates size and image format, and appends to the photo gallery.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    file_bytes = await file.read()
    return await WebsiteAnalysisService.upload_user_photo(
        db=db,
        user_id=uid,
        file_bytes=file_bytes,
        filename=file.filename or "upload.jpg",
        content_type=file.content_type or "image/jpeg"
    )


@router.post("/website-onboarding/complete", response_model=CompleteWebsiteOnboardingResponse)
@router.post("/website-analysis/complete", response_model=CompleteWebsiteOnboardingResponse)
async def complete_website_onboarding(current_user=Depends(get_current_user)):
    """
    Finalizes the website onboarding flow and transitions the user to the next step (Social Connectivity).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await WebsiteAnalysisService.complete_website_onboarding(db, uid)


# -----------------------------------------------------------------------------
# Business Categories & Subcategories
# -----------------------------------------------------------------------------

@router.get("/categories")
@router.get("/google-maps/categories")
async def get_onboarding_categories(q: Optional[str] = None):
    """
    Returns structured business categories and subcategories for the onboarding flow.
    Supports optional keyword search filter via ?q=.
    """
    if q and q.strip():
        return {"success": True, "data": search_categories(q.strip())}
    return {"success": True, "data": get_all_categories()}


@router.get("/subcategories")
@router.get("/google-maps/subcategories")
async def get_onboarding_subcategories(category_id: Optional[str] = None):
    """
    Returns subcategories, optionally filtered by category_id.
    """
    return {"success": True, "data": get_subcategories(category_id)}


# -----------------------------------------------------------------------------
# Google Maps Onboarding Endpoints
# -----------------------------------------------------------------------------

@router.get("/google-maps/search", response_model=GoogleMapsSearchResponse)
async def search_google_maps_businesses(
    query: str = Query(..., min_length=2, description="Shop or business name to search"),
    lat: Optional[float] = Query(None, description="Optional latitude for location bias"),
    lng: Optional[float] = Query(None, description="Optional longitude for location bias"),
    radius: Optional[float] = Query(50000.0, description="Search radius in meters"),
    current_user=Depends(get_current_user)
):
    """
    Searches Google Maps for businesses matching the query using Google Places API (New).
    Normalizes search input and returns matching businesses with place IDs, ratings, addresses, and photos.
    """
    return await GoogleMapsOnboardingService.search_businesses(
        query=query,
        latitude=lat,
        longitude=lng,
        radius=radius or 50000.0
    )


@router.post("/google-maps/search", response_model=GoogleMapsSearchResponse)
async def search_google_maps_businesses_post(
    payload: GoogleMapsSearchRequest,
    current_user=Depends(get_current_user)
):
    """
    POST variant for searching Google Maps businesses.
    """
    return await GoogleMapsOnboardingService.search_businesses(
        query=payload.query,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius=payload.radius or 50000.0
    )


@router.post("/google-maps/resolve-url", response_model=GoogleMapsResolveResponse)
async def resolve_google_maps_url(
    payload: GoogleMapsUrlResolveRequest,
    current_user=Depends(get_current_user)
):
    """
    Resolves a Google Maps link (including short links like maps.app.goo.gl and full place URLs)
    into a verified matching business with full details.
    """
    return await GoogleMapsOnboardingService.resolve_maps_url(str(payload.url))


@router.get("/google-maps/place/{place_id}", response_model=GoogleMapsPlaceItem)
async def get_google_maps_place_details(
    place_id: str,
    current_user=Depends(get_current_user)
):
    """
    Retrieves full details for a selected Google Place ID.
    """
    return await GoogleMapsOnboardingService.get_place_details(place_id)


@router.get("/google-maps/photo")
async def proxy_google_maps_photo(
    photo_name: str = Query(..., description="Google Places photo resource name"),
    max_width: int = Query(800, ge=100, le=1600, description="Max width in pixels")
):
    """
    Proxies Google Places photo media safely without exposing private API keys to the frontend.
    """
    redirect_url, image_bytes, content_type = await GoogleMapsOnboardingService.proxy_google_photo(photo_name, max_width)
    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return Response(content=image_bytes, media_type=content_type)


@router.post("/google-maps/select", response_model=GoogleMapsOnboardingState)
async def select_google_maps_business(
    payload: SelectGoogleMapsBusinessRequest,
    current_user=Depends(get_current_user)
):
    """
    Persists the selected Google Maps business to the authenticated user's workspace
    (updating businesses, brand_kits, and pending_users/users collections) and advances to Step 2 (Website).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.select_business(db, uid, payload)


@router.put("/google-maps/website", response_model=GoogleMapsOnboardingState)
@router.post("/google-maps/website", response_model=GoogleMapsOnboardingState)
async def save_google_maps_website(
    payload: GoogleMapsWebsiteRequest,
    current_user=Depends(get_current_user)
):
    """
    Saves or skips the business website URL, validating format and advancing to Step 3 (Category).
    Does not overwrite existing user-entered website if skipped.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.save_website(db, uid, payload)


@router.put("/google-maps/category", response_model=GoogleMapsOnboardingState)
@router.post("/google-maps/category", response_model=GoogleMapsOnboardingState)
async def save_google_maps_category(
    payload: GoogleMapsCategoryRequest,
    current_user=Depends(get_current_user)
):
    """
    Validates and persists the business category and optional subcategory. Advances to Step 4 (Profile).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.save_category(db, uid, payload)


@router.put("/google-maps/profile", response_model=GoogleMapsOnboardingState)
@router.post("/google-maps/profile", response_model=GoogleMapsOnboardingState)
async def save_google_maps_profile(
    payload: GoogleMapsProfileRequest,
    current_user=Depends(get_current_user)
):
    """
    Saves business profile details: required business name and promotion goal ("What should we promote?"),
    plus optional target audience, USPs/differentiators, and logo URL.
    Advances to Step 5 (Photos).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.save_profile_details(db, uid, payload)


@router.post("/google-maps/logo/upload")
async def upload_google_maps_logo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """
    Uploads and validates a business logo image (JPEG, PNG, WebP up to 10 MB).
    Updates businesses and brand_kits with the verified asset URL.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    file_bytes = await file.read()
    logo_url = await GoogleMapsOnboardingService.upload_logo(
        db=db,
        user_id=uid,
        file_bytes=file_bytes,
        filename=file.filename or "logo.png",
        content_type=file.content_type or "image/png"
    )
    return {"success": True, "logo_url": logo_url}


@router.delete("/google-maps/logo")
async def remove_google_maps_logo(current_user=Depends(get_current_user)):
    """
    Removes the business logo reference from the user's business profile and brand kit.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    await GoogleMapsOnboardingService.remove_logo(db, uid)
    return {"success": True, "message": "Logo removed successfully."}


@router.get("/google-maps/photos", response_model=GoogleMapsPhotosResponse)
async def get_google_maps_photos(current_user=Depends(get_current_user)):
    """
    Retrieves the list of photos (Google Maps photos + user uploads) and active selections.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.get_photos(db, uid)


@router.post("/google-maps/photos/upload", response_model=GoogleMapsPhotoItem)
async def upload_google_maps_photo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """
    Uploads an additional business photo to the onboarding gallery.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    file_bytes = await file.read()
    return await GoogleMapsOnboardingService.upload_photo(
        db=db,
        user_id=uid,
        file_bytes=file_bytes,
        filename=file.filename or "business_photo.jpg",
        content_type=file.content_type or "image/jpeg"
    )


@router.post("/google-maps/photos/select", response_model=GoogleMapsPhotosResponse)
async def select_google_maps_photos(
    payload: SelectGoogleMapsPhotosRequest,
    current_user=Depends(get_current_user)
):
    """
    Persists chosen photo selections (enforces max limit of 15 photos).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.select_photos(db, uid, payload.selected_photo_urls)


@router.delete("/google-maps/photos", response_model=GoogleMapsPhotosResponse)
async def remove_google_maps_photo(
    photo_url: str = Query(..., description="URL of the photo to remove"),
    current_user=Depends(get_current_user)
):
    """
    Removes a photo from the gallery and unselects it.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.remove_photo(db, uid, photo_url)


@router.get("/google-maps/state", response_model=GoogleMapsOnboardingState)
async def get_google_maps_onboarding_state(current_user=Depends(get_current_user)):
    """
    Retrieves the authenticated user's current Google Maps onboarding session state,
    enabling seamless resumption upon page refresh or re-login.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.get_onboarding_state(db, uid)


@router.post("/google-maps/complete", response_model=GoogleMapsOnboardingCompleteResponse)
async def complete_google_maps_onboarding(current_user=Depends(get_current_user)):
    """
    Validates required fields, finalizes Google Maps onboarding,
    and advances stepper to Step 3 (Social Connectivity).
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await GoogleMapsOnboardingService.complete_onboarding(db, uid)


# -----------------------------------------------------------------------------
# Marketplace Seller & Wholesale/B2B Platform Onboarding Endpoints
# -----------------------------------------------------------------------------

@router.get("/platforms/catalog", response_model=PlatformCatalogResponse)
@router.get("/platforms/options", response_model=PlatformCatalogResponse)
async def get_platform_catalog(
    onboarding_source: Optional[str] = Query(None, description="marketplace_seller | wholesale_b2b")
):
    """
    Returns the supported platform catalogues for Marketplace Seller or Wholesale/B2B directory onboarding.
    """
    return PlatformOnboardingService.get_catalog(onboarding_source)


@router.post("/platforms", response_model=PlatformOnboardingState)
@router.put("/platforms", response_model=PlatformOnboardingState)
@router.post("/marketplace-seller/platforms", response_model=PlatformOnboardingState)
@router.put("/marketplace-seller/platforms", response_model=PlatformOnboardingState)
@router.post("/wholesale-b2b/platforms", response_model=PlatformOnboardingState)
@router.put("/wholesale-b2b/platforms", response_model=PlatformOnboardingState)
async def save_platform_selections(
    payload: SavePlatformsRequest,
    current_user=Depends(get_current_user)
):
    """
    Validates and persists chosen platform selections for Marketplace Seller or Wholesale/B2B.
    Enforces 'None of these' mutual exclusivity, validates required custom name for 'Other',
    and optionally launches website analysis if storefront URL is provided.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await PlatformOnboardingService.save_platform_selections(db, uid, payload)


@router.get("/platforms", response_model=PlatformOnboardingState)
@router.get("/marketplace-seller/state", response_model=PlatformOnboardingState)
@router.get("/wholesale-b2b/state", response_model=PlatformOnboardingState)
async def get_platform_onboarding_state(current_user=Depends(get_current_user)):
    """
    Retrieves the authenticated user's current Marketplace or Wholesale/B2B onboarding state,
    enabling seamless resumption upon page refresh or re-login.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await PlatformOnboardingService.get_platform_onboarding_state(db, uid)


@router.post("/platforms/website", response_model=PlatformWebsiteSubmissionResponse)
@router.put("/platforms/website", response_model=PlatformWebsiteSubmissionResponse)
@router.post("/marketplace-seller/website", response_model=PlatformWebsiteSubmissionResponse)
@router.put("/marketplace-seller/website", response_model=PlatformWebsiteSubmissionResponse)
@router.post("/wholesale-b2b/website", response_model=PlatformWebsiteSubmissionResponse)
@router.put("/wholesale-b2b/website", response_model=PlatformWebsiteSubmissionResponse)
async def submit_platform_website_or_skip(
    payload: PlatformWebsiteSubmissionRequest,
    current_user=Depends(get_current_user)
):
    """
    Submits an optional storefront URL for analysis or records an explicit skip,
    without overwriting the user's marketplace_seller or wholesale_b2b onboarding source.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await PlatformOnboardingService.submit_platform_website(
        db=db,
        user_id=uid,
        website_url=payload.website_url,
        skip=payload.skip
    )


@router.post("/platforms/analyze-url", response_model=PlatformUrlAnalysisResponse)
async def analyze_single_platform_url(
    payload: PlatformUrlAnalysisRequest,
    current_user=Depends(get_current_user)
):
    """
    Submits or retries a single platform URL (e.g. Amazon storefront or IndiaMART catalog)
    with SSRF protection, updating the platform analysis status and discovering images.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await PlatformOnboardingService.analyze_single_platform_url(
        db=db,
        user_id=uid,
        platform_id=payload.platform_id,
        url=payload.url,
        onboarding_source=payload.onboarding_source
    )


# -----------------------------------------------------------------------------
# Shared First-Content & First-Post Generation Endpoints (Step 5)
# -----------------------------------------------------------------------------

@router.get("/first-post/source-images", response_model=FirstPostSourceImagesResponse)
async def get_first_post_source_images(current_user=Depends(get_current_user)):
    """
    Retrieves all available source images for the authenticated business,
    aggregating discovered website photos, Google Maps photos, Brand Kit assets,
    marketplace listing images, and uploaded assets.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await FirstPostService.get_available_source_images(db, uid)


@router.post("/first-post/upload-image", response_model=FirstPostImageUploadResponse)
async def upload_first_post_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """
    Securely uploads a new source image for first-post generation,
    validating supported formats (JPEG, PNG, WebP) and size limits.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    content = await file.read()
    return await FirstPostService.upload_image(
        db=db,
        user_id=uid,
        file_bytes=content,
        filename=file.filename or "first_post_image.jpg",
        content_type=file.content_type or "image/jpeg"
    )


@router.post("/first-post/generate", response_model=FirstPostJobResponse)
async def generate_first_post(
    payload: FirstPostGenerateRequest,
    current_user=Depends(get_current_user)
):
    """
    Creates a persistent first-content generation job.
    Supports Post Maker, AI Photo Shoot, and Reel Maker.
    Generates 3 preview variations with backend-enforced entitlement (1 unlocked + 2 locked for free plans).
    Saves the unlocked preview into 'contents' collection so the Create Post dashboard can load it in edit mode.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await FirstPostService.create_generation_job(db, uid, payload)


@router.get("/first-post/status/{job_id}", response_model=FirstPostJobResponse)
async def get_first_post_status(
    job_id: str,
    current_user=Depends(get_current_user)
):
    """
    Polls the real-time processing status and 3 preview items for a first post generation job.
    Validates authenticated business ownership and re-evaluates plan locks.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    return await FirstPostService.get_job_status(db, job_id, uid)


@router.get("/first-post/latest", response_model=FirstPostJobResponse)
async def get_latest_first_post(current_user=Depends(get_current_user)):
    """
    Retrieves the most recent first-post generation job for the user,
    enabling seamless resumption on page reload.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    job = await FirstPostService.get_latest_job(db, uid)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No first post generation jobs found for this account."
        )
    return job


@router.post("/first-content/choice", response_model=FirstContentChoiceResponse)
async def set_first_content_choice(
    payload: FirstContentChoiceRequest,
    current_user=Depends(get_current_user)
):
    """
    Records the user's choice among the 3 first-content creation experiences:
    Post Maker, AI Photo Shoot, or Reel Maker.
    """
    db = get_database()
    uid = str(current_user.get("id"))
    now = datetime.now(timezone.utc)
    choice = payload.content_choice.lower().strip()

    valid_choices = {"post_maker", "ai_photoshoot", "reel_maker"}
    if choice not in valid_choices:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content choice '{choice}'. Must be one of: {', '.join(valid_choices)}."
        )

    await db["businesses"].update_one(
        {"$or": [{"owner_id": uid}, {"ownerId": uid}]},
        {"$set": {
            "first_content_choice": choice,
            "updated_at": now
        }},
        upsert=True
    )

    routes = {
        "post_maker": "/onboarding/first-post",
        "ai_photoshoot": "/onboarding/ai-photoshoot",
        "reel_maker": "/onboarding/reel-maker"
    }

    return FirstContentChoiceResponse(
        success=True,
        content_choice=choice,
        next_action=f"Proceed to generate your first content with {choice.replace('_', ' ').title()}",
        route=routes.get(choice, "/onboarding/first-post")
    )




