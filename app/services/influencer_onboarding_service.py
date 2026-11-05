import re
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.repositories.influencer_onboarding_repository import InfluencerOnboardingRepository
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
)

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
RESERVED_USERNAMES = {
    "admin", "root", "system", "help", "support", "dashboard", "creator", "influencer",
    "business", "settings", "profile", "explore", "discover", "api", "auth", "login",
    "signup", "logout", "onboarding", "dhandagrow", "sevenunique"
}


class InfluencerOnboardingService:
    """
    Service layer orchestrating the 7-screen Influencer Creator Onboarding flow.
    Enforces progressive MongoDB persistence, username normalization, and completion validation.
    """

    @classmethod
    def validate_username_format(cls, username: str) -> str:
        """Validate and normalize a proposed creator handle."""
        if not username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is required."
            )
        normalized = username.strip().lstrip("@").lower()
        if len(normalized) < 3 or len(normalized) > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be between 3 and 30 characters long."
            )
        if not USERNAME_REGEX.match(normalized):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username may only contain letters, numbers, and underscores."
            )
        if normalized in RESERVED_USERNAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The username '{normalized}' is reserved. Please choose another."
            )
        return normalized

    @classmethod
    async def check_username_availability(cls, raw_username: str, user_id: Optional[str] = None) -> UsernameCheckResponse:
        """Check format and database availability for a creator username."""
        try:
            normalized = cls.validate_username_format(raw_username)
        except HTTPException as exc:
            return UsernameCheckResponse(
                available=False,
                username=raw_username,
                message=exc.detail
            )

        exists = await InfluencerOnboardingRepository.check_username_exists(
            username=normalized,
            exclude_user_id=user_id
        )
        if exists:
            return UsernameCheckResponse(
                available=False,
                username=normalized,
                message=f"The username '@{normalized}' is already taken."
            )

        return UsernameCheckResponse(
            available=True,
            username=normalized,
            message=f"The username '@{normalized}' is available!"
        )

    @classmethod
    async def get_state(cls, user_id: str) -> InfluencerOnboardingStateResponse:
        """
        Retrieve existing progress for the authenticated user to restore entered values on page mount.
        """
        doc = await InfluencerOnboardingRepository.get_by_user_id(user_id) or {}

        # Extract profile fields
        profile_data = {
            "full_name": doc.get("full_name") or doc.get("fullName"),
            "username": doc.get("username"),
            "bio": doc.get("bio"),
            "location": doc.get("location"),
            "gender": doc.get("gender"),
            "profile_image": doc.get("profile_image") or doc.get("profileImageUrl"),
        }

        # Extract niches
        niches_data = {
            "niches": doc.get("niches", []),
            "primary_niche": doc.get("primary_niche") or doc.get("category"),
            "custom_niche": doc.get("custom_niche"),
        }

        # Extract social accounts
        social_accounts_data = doc.get("social_accounts") or {
            "instagram": {"url": doc.get("instagram_url"), "handle": None, "connected": bool(doc.get("instagram_url")), "verified": False},
            "facebook": {"url": doc.get("facebook_url"), "handle": None, "connected": bool(doc.get("facebook_url")), "verified": False},
            "linkedin": {"url": doc.get("linkedin_url"), "handle": None, "connected": bool(doc.get("linkedin_url")), "verified": False},
            "youtube": {"url": doc.get("youtube_url"), "handle": None, "connected": bool(doc.get("youtube_url")), "verified": False},
            "tiktok": {"url": None, "handle": None, "connected": False, "verified": False},
        }

        goals_data = doc.get("goals", [])
        status_val = doc.get("onboarding_status", "NOT_STARTED")
        current_step = doc.get("current_step", 1)
        completed_steps = doc.get("completed_steps", [])

        return InfluencerOnboardingStateResponse(
            user_id=str(user_id),
            onboarding_status=status_val,
            current_step=current_step,
            completed_steps=completed_steps,
            profile=profile_data,
            niches=niches_data,
            social_accounts=social_accounts_data,
            goals=goals_data,
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    @classmethod
    async def save_profile_step(cls, user_id: str, request: ProfileStepRequest) -> InfluencerOnboardingStateResponse:
        """
        Progressively save Step 2 Profile Information.
        Validates username uniqueness if a username is supplied.
        """
        updates: Dict[str, Any] = {}

        if request.full_name is not None:
            updates["full_name"] = request.full_name.strip()
            updates["fullName"] = request.full_name.strip()

        if request.username is not None and request.username.strip():
            normalized = cls.validate_username_format(request.username)
            is_taken = await InfluencerOnboardingRepository.check_username_exists(normalized, exclude_user_id=user_id)
            if is_taken:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Username '@{normalized}' is already in use by another creator."
                )
            updates["username"] = normalized

        if request.bio is not None:
            updates["bio"] = request.bio.strip()

        if request.location is not None:
            updates["location"] = request.location.strip()

        if request.gender is not None:
            updates["gender"] = request.gender.strip()

        if request.profile_image is not None:
            updates["profile_image"] = request.profile_image.strip()

        await InfluencerOnboardingRepository.partial_save(user_id, updates, step_number=2)
        return await cls.get_state(user_id)

    @classmethod
    async def save_niches_step(cls, user_id: str, request: NichesStepRequest) -> InfluencerOnboardingStateResponse:
        """Progressively save Step 3 Creator Niches."""
        updates: Dict[str, Any] = {}

        if request.niches is not None:
            cleaned_niches = [n.strip() for n in request.niches if n and n.strip()]
            updates["niches"] = cleaned_niches
            if cleaned_niches and not request.primary_niche:
                updates["primary_niche"] = cleaned_niches[0]
                updates["category"] = cleaned_niches[0]

        if request.primary_niche is not None:
            updates["primary_niche"] = request.primary_niche.strip()
            updates["category"] = request.primary_niche.strip()

        if request.custom_niche is not None:
            updates["custom_niche"] = request.custom_niche.strip()

        await InfluencerOnboardingRepository.partial_save(user_id, updates, step_number=3)
        return await cls.get_state(user_id)

    @classmethod
    async def save_social_accounts_step(cls, user_id: str, request: SocialAccountsStepRequest) -> InfluencerOnboardingStateResponse:
        """Progressively save Step 4 Connected Social Accounts."""
        # Retrieve existing social accounts to merge without erasing
        existing_doc = await InfluencerOnboardingRepository.get_by_user_id(user_id) or {}
        existing_socials = existing_doc.get("social_accounts") or {}

        def _default_platform_item():
            return {"handle": None, "url": None, "connected": False, "verified": False}

        def _merge_platform(field_name: str, new_val):
            current = dict(existing_socials.get(field_name) or _default_platform_item())
            if new_val is not None:
                dumped = new_val.model_dump(exclude_unset=True)
                current.update(dumped)
            return current

        socials_payload = {
            "instagram": _merge_platform("instagram", request.instagram),
            "facebook": _merge_platform("facebook", request.facebook),
            "linkedin": _merge_platform("linkedin", request.linkedin),
            "youtube": _merge_platform("youtube", request.youtube),
            "tiktok": _merge_platform("tiktok", request.tiktok),
        }

        updates: Dict[str, Any] = {"social_accounts": socials_payload}

        # Keep top-level legacy fields in sync for backward compatibility with marketplace search
        if request.instagram and request.instagram.url:
            updates["instagram_url"] = request.instagram.url
        if request.facebook and request.facebook.url:
            updates["facebook_url"] = request.facebook.url
        if request.linkedin and request.linkedin.url:
            updates["linkedin_url"] = request.linkedin.url
        if request.youtube and request.youtube.url:
            updates["youtube_url"] = request.youtube.url

        await InfluencerOnboardingRepository.partial_save(user_id, updates, step_number=4)
        return await cls.get_state(user_id)

    @classmethod
    async def save_goals_step(cls, user_id: str, request: GoalsStepRequest) -> InfluencerOnboardingStateResponse:
        """Progressively save Step 5 Creator Goals."""
        updates: Dict[str, Any] = {}
        if request.goals is not None:
            updates["goals"] = [g.strip() for g in request.goals if g and g.strip()]

        await InfluencerOnboardingRepository.partial_save(user_id, updates, step_number=5)
        return await cls.get_state(user_id)

    @classmethod
    async def save_progress(cls, user_id: str, request: ProgressStepRequest) -> InfluencerOnboardingStateResponse:
        """Update current step pointer and completed steps list."""
        await InfluencerOnboardingRepository.update_progress(
            user_id=user_id,
            current_step=request.current_step,
            completed_steps=request.completed_steps
        )
        return await cls.get_state(user_id)

    @classmethod
    async def get_review_data(cls, user_id: str) -> InfluencerReviewResponse:
        """
        Aggregate all saved creator details for Screen 6 Review and evaluate readiness to complete.
        """
        state = await cls.get_state(user_id)
        profile = state.profile
        niches = state.niches
        socials = state.social_accounts
        goals = state.goals

        missing: List[str] = []
        if not profile.get("full_name"):
            missing.append("Full Name")
        if not profile.get("username"):
            missing.append("Creator Username")
        if not niches.get("niches") or len(niches.get("niches")) == 0:
            missing.append("At least one Creator Niche")
        if not goals or len(goals) == 0:
            missing.append("At least one Creator Goal")

        can_complete = len(missing) == 0

        summary = {
            "profile": profile,
            "niches": niches,
            "social_accounts": socials,
            "goals": goals,
            "current_step": state.current_step,
            "completed_steps": state.completed_steps,
        }

        return InfluencerReviewResponse(
            user_id=str(user_id),
            can_complete=can_complete,
            missing_requirements=missing,
            summary=summary,
        )

    @classmethod
    async def complete_onboarding(cls, user_id: str) -> OnboardingCompleteResponse:
        """
        Finalize Influencer Onboarding:
        1. Validates that mandatory requirements are satisfied.
        2. Sets onboarding_status = 'COMPLETED' in influencer_profiles.
        3. Updates user document with onboardingCompleted = True, role = 'influencer'.
        4. Returns redirect URL to /influencer.
        """
        review = await cls.get_review_data(user_id)
        if not review.can_complete:
            missing_str = ", ".join(review.missing_requirements)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot complete creator onboarding. Missing required information: {missing_str}."
            )

        final_profile = await InfluencerOnboardingRepository.finalize_onboarding(user_id)
        return OnboardingCompleteResponse(
            message="Influencer creator onboarding completed successfully! Welcome to DhandaGrow AI.",
            redirect_url="/influencer",
            user_id=str(user_id),
            onboarding_status="COMPLETED",
            profile=final_profile,
        )
