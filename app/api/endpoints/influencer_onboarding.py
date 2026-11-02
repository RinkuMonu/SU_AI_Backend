import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from app.core.security import get_current_user, CurrentUser
from app.services.influencer_onboarding_service import InfluencerOnboardingService
from app.schemas.influencer_onboarding import (
    ProfileStepRequest,
    NichesStepRequest,
    SocialAccountsStepRequest,
    GoalsStepRequest,
    ProgressStepRequest,
    UsernameCheckResponse,
    InfluencerOnboardingStateResponse,
    InfluencerReviewResponse,
    OnboardingCompleteResponse,
    AvatarUploadResponse,
)

router = APIRouter(tags=["Influencer Onboarding"])


def _extract_user_id(current_user: CurrentUser) -> str:
    """Securely extract user ID from authenticated token context."""
    user_id = getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials."
        )
    return str(user_id)


# ---------------------------------------------------------------------------
# 1. State & Username Availability
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=InfluencerOnboardingStateResponse,
    summary="Get saved influencer onboarding state",
    description="Retrieve previously saved onboarding progress and form values to restore state on mount or re-login."
)
async def get_onboarding_state(
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.get_state(user_id)


@router.get(
    "/check-username",
    response_model=UsernameCheckResponse,
    summary="Check creator username availability",
    description="Live debounced uniqueness check for creator username. Excludes the current user's profile."
)
async def check_username(
    username: str = Query(..., min_length=1, max_length=50, description="Proposed creator handle"),
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.check_username_availability(username, user_id=user_id)


# ---------------------------------------------------------------------------
# 2. Progressive Step Updates (MongoDB $set)
# ---------------------------------------------------------------------------

@router.patch(
    "/profile",
    response_model=InfluencerOnboardingStateResponse,
    summary="Save Step 2: Creator Profile",
    description="Progressively save creator name, unique handle, bio, location, gender, and profile photo without erasing other fields."
)
async def save_profile(
    request: ProfileStepRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.save_profile_step(user_id, request)


@router.patch(
    "/niches",
    response_model=InfluencerOnboardingStateResponse,
    summary="Save Step 3: Creator Niches",
    description="Progressively save selected niches and custom niche options."
)
async def save_niches(
    request: NichesStepRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.save_niches_step(user_id, request)


@router.patch(
    "/social-accounts",
    response_model=InfluencerOnboardingStateResponse,
    summary="Save Step 4: Social Accounts",
    description="Progressively save social platform handles/URLs (Instagram, YouTube, TikTok, Facebook)."
)
async def save_social_accounts(
    request: SocialAccountsStepRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.save_social_accounts_step(user_id, request)


@router.patch(
    "/goals",
    response_model=InfluencerOnboardingStateResponse,
    summary="Save Step 5: Creator Goals",
    description="Progressively save selected creator goals on DhandaGrow AI."
)
async def save_goals(
    request: GoalsStepRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.save_goals_step(user_id, request)


@router.patch(
    "/progress",
    response_model=InfluencerOnboardingStateResponse,
    summary="Update Onboarding Step Progress",
    description="Update the current active screen (1-7) and completed steps list without modifying form values."
)
async def save_progress(
    request: ProgressStepRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.save_progress(user_id, request)


# ---------------------------------------------------------------------------
# 3. Review & Completion
# ---------------------------------------------------------------------------

@router.get(
    "/review",
    response_model=InfluencerReviewResponse,
    summary="Get Step 6 Review Summary",
    description="Retrieve an aggregated summary of all entered details for final verification before submission."
)
async def get_review(
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.get_review_data(user_id)


@router.post(
    "/complete",
    response_model=OnboardingCompleteResponse,
    summary="Finalize Creator Onboarding (Step 7)",
    description="Validate all required creator fields, finalize profile in MongoDB, mark user onboardingCompleted=True, and transition to /influencer."
)
async def complete_onboarding(
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = _extract_user_id(current_user)
    return await InfluencerOnboardingService.complete_onboarding(user_id)


# ---------------------------------------------------------------------------
# 4. Avatar Upload
# ---------------------------------------------------------------------------

@router.post(
    "/avatar",
    response_model=AvatarUploadResponse,
    summary="Upload Creator Profile Photo",
    description="Upload an avatar image to /uploads/avatars/ and receive a public URL to store in the creator profile."
)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user)
):
    _extract_user_id(current_user)

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a valid image (JPEG, PNG, WEBP)."
        )

    # 10 MB limit
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size exceeds maximum limit of 10 MB."
        )

    upload_dir = os.path.join("uploads", "avatars")
    os.makedirs(upload_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    unique_name = f"avatar_{uuid.uuid4().hex[:12]}{ext}"
    dest_path = os.path.join(upload_dir, unique_name)

    with open(dest_path, "wb") as f:
        f.write(content)

    public_url = f"/uploads/avatars/{unique_name}"
    return AvatarUploadResponse(
        success=True,
        url=public_url,
        filename=unique_name,
        message="Profile photo uploaded successfully."
    )

