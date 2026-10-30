import logging
import secrets
import urllib.parse
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from fastapi import APIRouter, Depends, status, Request, Response, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import EmailStr
import jwt

from app.core.config import settings
from app.core.database import get_database
from app.core.security import (
    create_access_token,
    get_current_user,
    get_current_user_optional,
    CurrentUser,
    require_businessman,
    require_influencer,
    require_completed_onboarding,
)
from app.services.onboarding_service import OnboardingService
from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    SendOTPRequest,
    VerifyOTPRequest,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    FacebookAuthLoginRequest,
    InstagramAuthLoginRequest,
    LinkedInAuthLoginRequest,
)
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    OTPVerifyRequest,
    OTPResendRequest,
    RoleSelectRequest,
    RoleSelectResponse,
    DashboardRouteResponse,
)
from app.services.auth_service import (
    AuthService,
    PhoneNotVerifiedException,
    EmailNotVerifiedException,
)
from app.services.facebook_service import FacebookService
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

def set_refresh_cookie(response: Response, refresh_token: str):
    is_live = (
        settings.ENVIRONMENT == "production"
        or (settings.FRONTEND_URL and settings.FRONTEND_URL.startswith("https://"))
        or (settings.BACKEND_URL and settings.BACKEND_URL.startswith("https://"))
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_live,
        samesite="none" if is_live else "lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def signup(request: Request, response: Response):
    body = await request.json()
    
    raw_phone = body.get("phone_number") or body.get("phone") or body.get("mobile") or body.get("contactNumber")
    raw_email = (body.get("email") or "").lower().strip()
    raw_otp = body.get("otp")
    
    db = get_database()
    
    # Check duplicate email
    if raw_email:
        existing = await db["users"].find_one({"email": raw_email})
        if existing and (existing.get("emailVerified") or existing.get("email_verified") or existing.get("phone_verified") or existing.get("hashed_password")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email is already registered. Please log in."
            )

    # Check duplicate mobile number
    v_token = body.get("verification_token")
    if raw_phone:
        from app.utils.phone import normalize_phone_number, InvalidPhoneNumberException
        try:
            norm_p = normalize_phone_number(str(raw_phone).strip())
            existing_p = await db["users"].find_one({"phone_number": norm_p})
            if existing_p and existing_p.get("email") and existing_p.get("hashed_password"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this mobile number already exists. Please log in."
                )
            elif existing_p and not v_token:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this mobile number already exists. Please log in."
                )
        except InvalidPhoneNumberException:
            pass
            
    # If raw_otp is provided or firstName+lastName without phone OTP requirement
    if raw_otp or (body.get("firstName") and body.get("lastName")) or (body.get("fullName") and not raw_phone):
        from app.schemas.auth import SignupRequest
        try:
            req = SignupRequest(**body)
            user, access_token, refresh_token = await AuthService.signup(req)
            set_refresh_cookie(response, refresh_token)
            user_dict = {
                "id": str(user.id),
                "fullName": user.fullName or user.name or "User",
                "name": user.fullName or user.name or "User",
                "firstName": user.firstName,
                "lastName": user.lastName,
                "email": user.email,
                "phone": user.phone or user.contactNumber,
                "contactNumber": user.contactNumber or user.phone,
                "accountType": user.accountType,
                "role": getattr(user, "role", "user") or "user",
                "emailVerified": bool(user.emailVerified),
                "email_verified": bool(user.emailVerified),
                "isVerified": bool(user.emailVerified),
                "onboardingCompleted": False,
                "onboarding_completed": False,
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "can_access_dashboard": False,
                "next_step": "role_selection"
            }
            response.status_code = status.HTTP_200_OK
            return {
                "success": True,
                "message": "User registered successfully.",
                "access_token": access_token,
                "accessToken": access_token,
                "token": access_token,
                "user": user_dict,
                "requires_role_selection": True,
                "dashboard_route": "/select-role",
                "onboarding_status": "not_started",
                "onboarding_step": 1,
                "online_presence": None,
                "can_access_dashboard": False,
                "next_step": "role_selection",
                "data": {
                    "access_token": access_token,
                    "accessToken": access_token,
                    "token": access_token,
                    "user": user_dict,
                    "requires_role_selection": True,
                    "dashboard_route": "/select-role",
                    "onboarding_status": "not_started",
                    "onboarding_step": 1,
                    "online_presence": None,
                    "can_access_dashboard": False,
                    "next_step": "role_selection"
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Fallback to UserCreate for signup: {e}")

    # Phone signup flow
    from pydantic import ValidationError
    from fastapi.exceptions import RequestValidationError
    try:
        user_in = UserCreate(**body)
    except ValidationError as ve:
        raise RequestValidationError(ve.errors())
    result = await AuthService.handle_signup(user_in)
    return result


@router.post("/verify-otp")
@router.post("/otp/verify-phone")
async def verify_otp(request: OTPVerifyRequest, response: Response = None):
    identifier = request.phone_number or request.phone or request.mobile or (str(request.email) if request.email else None)
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number or identifier is required for OTP verification."
        )

    cc = request.country_code or request.countryCode
    channel = request.channel or "sms"
    mode = request.mode
    result = await AuthService.verify_otp(identifier, request.otp, country_code=cc, channel=channel, mode=mode)

    user = result if isinstance(result, User) else None
    if isinstance(result, dict) and "user" in result and isinstance(result["user"], User):
        user = result["user"]

    v_token = getattr(user, "phone_verification_token", None) or getattr(user, "verification_token", None)
    if not v_token and isinstance(result, dict):
        v_token = result.get("verification_token") or result.get("phone_verification_token")
    if not v_token:
        db = get_database()
        user_phone = (getattr(user, "phone_number", None) if user else None) or identifier
        pv_doc = await db["phone_verifications"].find_one({"phone_number": user_phone}, sort=[("_id", -1)])
        if pv_doc:
            v_token = pv_doc.get("verification_token")
        if not v_token:
            v_token = secrets.token_urlsafe(32)
            await db["phone_verifications"].insert_one({
                "phone_number": user_phone,
                "verification_token": v_token,
                "verified": True,
                "channel": channel,
                "verified_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
                "used": False,
                "user_id": str(user.id) if user else None
            })

    if not user:
        if isinstance(result, User):
            user = result
        else:
            users_col = await AuthService.get_collection()
            clean_id = str(identifier).strip()
            user_doc = await users_col.find_one({"phone_number": clean_id})
            if user_doc:
                user = User(**user_doc)

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification failed.")

    db = get_database()
    jwt_access_token, jwt_refresh_token = await AuthService.create_session(db, str(user.id))
    if response:
        set_refresh_cookie(response, jwt_refresh_token)

    u_dict = user.model_dump() if hasattr(user, "model_dump") else (user.dict() if hasattr(user, "dict") else dict(user))
    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user.id)}, {"ownerId": str(user.id)}]})
    onb_state = OnboardingService.determine_state(u_dict, bus_doc)

    role = onb_state.get("role")
    requires_role = onb_state["requires_role_selection"]
    dashboard_route = "/select-role" if requires_role else ("/influencer" if role == "influencer" else "/dashboard")

    user_resp = UserResponse(
        id=str(user.id),
        name=user.name,
        phone_number=getattr(user, "phone_number", None),
        phone_verified=getattr(user, "phone_verified", True),
        email=getattr(user, "email", None),
        role=role,
        email_verified=getattr(user, "email_verified", True),
        online_presence=onb_state.get("online_presence"),
        onboarding_step=onb_state.get("onboarding_step", 1),
        onboarding_status=onb_state.get("onboarding_status", "not_started"),
        onboardingCompleted=onb_state.get("onboarding_completed", False),
        onboarding_completed_at=getattr(user, "onboarding_completed_at", None)
    )
    return TokenResponse(
        access_token=jwt_access_token,
        token=jwt_access_token,
        user=user_resp,
        role=role,
        phone_verified=True,
        requires_role_selection=requires_role,
        dashboard_route=dashboard_route,
        phone_verification_token=v_token,
        verification_token=v_token,
        next_step=onb_state["next_step"],
        online_presence=onb_state.get("online_presence"),
        onboarding_step=onb_state.get("onboarding_step", 1),
        onboarding_status=onb_state.get("onboarding_status", "not_started"),
        can_access_dashboard=onb_state["can_access_dashboard"],
        onboarding_completed=onb_state["onboarding_completed"],
        onboardingCompleted=onb_state["onboarding_completed"],
        success=True,
        message="OTP verified successfully. Logged in."
    )


@router.post("/send-otp")
@router.post("/resend-otp")
@router.post("/otp/send-phone")
async def resend_otp(request: OTPResendRequest):
    identifier = request.phone_number or request.phone or request.mobile or (str(request.email) if request.email else None)
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number or identifier is required to send OTP."
        )

    cc = request.country_code or request.countryCode
    channel = request.channel or "sms"
    mode = request.mode
    result = await AuthService.resend_otp(identifier, country_code=cc, channel=channel, mode=mode)
    return result




@router.post("/login")
async def login(request: Request, response: Response):
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = body.get("email")
    phone = body.get("phone_number") or body.get("phone") or body.get("mobile") or body.get("username")
    country_code = body.get("country_code") or body.get("countryCode")
    password = body.get("password")
    
    if not password:
        raise HTTPException(status_code=400, detail="Password is required.")

    from pydantic import ValidationError
    from fastapi.exceptions import RequestValidationError
    try:
        user_in = UserLogin(phone_number=phone, email=email, password=password, country_code=country_code)
    except ValidationError as ve:
        raise RequestValidationError(ve.errors())

    try:
        user = await AuthService.authenticate_user(user_in)
    except PhoneNotVerifiedException as e:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(e), "code": "PHONE_NOT_VERIFIED"}
        )
    except HTTPException as auth_exc:
        if email and "@" in str(email):
            try:
                from app.schemas.auth import LoginRequest
                login_req = LoginRequest(email=email, password=password)
                user, access_token, refresh_token = await AuthService.login(login_req)
                set_refresh_cookie(response, refresh_token)
                u_phone = getattr(user, "phone", None) or getattr(user, "phone_number", None)
                u_role = getattr(user, "role", "user")
                u_pv = getattr(user, "phone_verified", False)
                if not u_phone or u_role in ["businessman", "influencer", "admin"]:
                    u_pv = True

                user_dict = {
                    "id": str(user.id),
                    "fullName": getattr(user, "fullName", None) or getattr(user, "name", None) or "User",
                    "name": getattr(user, "name", None) or getattr(user, "fullName", None) or "User",
                    "email": getattr(user, "email", None),
                    "phone": u_phone,
                    "phone_number": u_phone,
                    "role": u_role,
                    "email_verified": getattr(user, "email_verified", True),
                    "phone_verified": u_pv,
                }
                return {
                    "success": True,
                    "message": "Logged in successfully",
                    "access_token": access_token,
                    "accessToken": access_token,
                    "token": access_token,
                    "user": user_dict,
                    "data": {
                        "access_token": access_token,
                        "accessToken": access_token,
                        "token": access_token,
                        "user": user_dict
                    }
                }
            except Exception:
                raise auth_exc
        raise auth_exc

    access_token = create_access_token(subject=str(user.id))
    u_phone = getattr(user, "phone_number", None) or getattr(user, "phone", None)
    u_role = getattr(user, "role", None)
    u_pv = getattr(user, "phone_verified", False)
    if not u_phone or u_role in ["businessman", "influencer", "admin"]:
        u_pv = True

    user_dict = {
        "id": str(user.id),
        "name": user.name,
        "fullName": getattr(user, "fullName", None) or user.name,
        "email": getattr(user, "email", None),
        "phone_number": u_phone,
        "phone": u_phone,
        "role": u_role,
        "phone_verified": u_pv,
        "email_verified": getattr(user, "email_verified", True),
    }
    
    try:
        refresh_token = AuthService.create_token(str(user.id), settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
        set_refresh_cookie(response, refresh_token)
    except Exception as e:
        logger.error(f"Failed to set refresh cookie in login: {e}")
        
    db = get_database()
    u_dict = user.model_dump() if hasattr(user, "model_dump") else (user.dict() if hasattr(user, "dict") else dict(user))
    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user.id)}, {"ownerId": str(user.id)}]})
    onb_state = OnboardingService.determine_state(u_dict, bus_doc)

    role = onb_state.get("role")
    requires_role = onb_state["requires_role_selection"]
    dashboard_route = "/select-role" if requires_role else ("/influencer" if role == "influencer" else "/dashboard")

    user_dict["online_presence"] = onb_state.get("online_presence")
    user_dict["onboarding_step"] = onb_state.get("onboarding_step", 1)
    user_dict["onboarding_status"] = onb_state.get("onboarding_status", "not_started")
    user_dict["onboardingCompleted"] = onb_state.get("onboarding_completed", False)
    user_dict["onboarding_completed"] = onb_state.get("onboarding_completed", False)
    user_dict["can_access_dashboard"] = onb_state["can_access_dashboard"]
    user_dict["next_step"] = onb_state["next_step"]

    return {
        "success": True,
        "access_token": access_token,
        "accessToken": access_token,
        "token_type": "bearer",
        "user": user_dict,
        "role": role,
        "requires_role_selection": requires_role,
        "dashboard_route": dashboard_route,
        "onboarding_status": onb_state.get("onboarding_status", "not_started"),
        "onboarding_step": onb_state.get("onboarding_step", 1),
        "online_presence": onb_state.get("online_presence"),
        "onboardingCompleted": onb_state.get("onboarding_completed", False),
        "onboarding_completed": onb_state.get("onboarding_completed", False),
        "can_access_dashboard": onb_state["can_access_dashboard"],
        "next_step": onb_state["next_step"],
        "data": {
            "access_token": access_token,
            "accessToken": access_token,
            "token": access_token,
            "user": user_dict,
            "role": role,
            "requires_role_selection": requires_role,
            "dashboard_route": dashboard_route,
            "onboarding_status": onb_state.get("onboarding_status", "not_started"),
            "onboarding_step": onb_state.get("onboarding_step", 1),
            "online_presence": onb_state.get("online_presence"),
            "onboardingCompleted": onb_state.get("onboarding_completed", False),
            "onboarding_completed": onb_state.get("onboarding_completed", False),
            "can_access_dashboard": onb_state["can_access_dashboard"],
            "next_step": onb_state["next_step"]
        }
    }


@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_in = UserLogin(username=form_data.username, password=form_data.password)
    try:
        user = await AuthService.authenticate_user(user_in)
    except PhoneNotVerifiedException as e:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(e), "code": "PHONE_NOT_VERIFIED"}
        )

    access_token = create_access_token(subject=str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    """
    Canonical endpoint to fetch current authenticated user profile.
    Compatible with direct user dictionary format, UserResponse schema, and ApiResponse envelope.
    """
    db = get_database()
    user_id = str(current_user.get("id") or current_user.get("_id"))
    doc = None
    if ObjectId.is_valid(user_id):
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        if not doc:
            doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        doc = current_user

    uid = str(doc.get("_id") or doc.get("id") or user_id)
    full_name = doc.get("fullName") or doc.get("name") or "User"
    user_phone = doc.get("phone_number") or doc.get("phone") or doc.get("contactNumber")
    phone_verified = doc.get("phone_verified", True if not user_phone else False)
    if not user_phone or doc.get("role") in ["businessman", "influencer", "admin"]:
        phone_verified = True
    email_ver = bool(doc.get("emailVerified", doc.get("email_verified", True)))

    user_dict = {
        "id": uid,
        "_id": uid,
        "fullName": full_name,
        "name": full_name,
        "firstName": doc.get("firstName") or full_name.split()[0],
        "lastName": doc.get("lastName") or (" ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else None),
        "email": doc.get("email") or None,
        "phone_number": user_phone,
        "phone": user_phone,
        "contactNumber": user_phone,
        "phone_verified": phone_verified,
        "accountType": doc.get("accountType", "business"),
        "role": doc.get("role", "businessman") or "businessman",
        "emailVerified": email_ver,
        "email_verified": email_ver,
        "isVerified": email_ver,
        "profileImageUrl": doc.get("profileImageUrl") or doc.get("image") or doc.get("avatar"),
        "image": doc.get("image") or doc.get("profileImageUrl") or doc.get("avatar"),
        "avatar": doc.get("avatar") or doc.get("profileImageUrl") or doc.get("image"),
        "preferredLanguage": doc.get("preferredLanguage"),
        "businessName": doc.get("businessName") or doc.get("business_name"),
        "onboardingCompleted": doc.get("onboardingCompleted", False),
        "onboarding_step": doc.get("onboarding_step", 1),
    }

    return {
        **user_dict,
        "success": True,
        "data": user_dict,
    }


@router.post("/select-role", response_model=RoleSelectResponse)
@router.post("/role", response_model=RoleSelectResponse)
async def select_role(
    request: RoleSelectRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    user_id = str(current_user["id"])
    updated_user = await AuthService.select_role(
        user_id=user_id,
        requested_role=request.role,
        client_user_id=request.user_id
    )

    db = get_database()
    u_dict = updated_user.model_dump() if hasattr(updated_user, "model_dump") else (updated_user.dict() if hasattr(updated_user, "dict") else dict(updated_user))
    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": user_id}, {"ownerId": user_id}]})
    onb_state = OnboardingService.determine_state(u_dict, bus_doc)

    user_resp = UserResponse(
        id=str(updated_user.id),
        name=updated_user.name,
        phone_number=getattr(updated_user, "phone_number", None),
        phone_verified=getattr(updated_user, "phone_verified", False),
        email=getattr(updated_user, "email", None),
        role=getattr(updated_user, "role", None),
        email_verified=getattr(updated_user, "email_verified", True),
        online_presence=onb_state.get("online_presence"),
        onboarding_step=onb_state.get("onboarding_step", 1),
        onboarding_status=onb_state.get("onboarding_status", "not_started"),
        onboardingCompleted=onb_state.get("onboarding_completed", False),
        onboarding_completed_at=getattr(updated_user, "onboarding_completed_at", None)
    )

    return RoleSelectResponse(
        id=user_resp.id,
        name=user_resp.name,
        phone_number=user_resp.phone_number,
        phone_verified=user_resp.phone_verified,
        email=user_resp.email,
        role=user_resp.role,
        email_verified=user_resp.email_verified,
        online_presence=onb_state.get("online_presence"),
        onboarding_step=onb_state.get("onboarding_step", 1),
        onboarding_status=onb_state.get("onboarding_status", "not_started"),
        onboardingCompleted=onb_state.get("onboarding_completed", False),
        dashboard_route=onb_state["dashboard_route"],
        next_step=onb_state["next_step"],
        can_access_dashboard=onb_state["can_access_dashboard"],
        success=True,
        message="Role selected successfully.",
        user=user_resp
    )


@router.get("/dashboard-route", response_model=DashboardRouteResponse)
@router.get("/dashboard")
async def get_dashboard_route(current_user: CurrentUser = Depends(get_current_user)):
    role = current_user.get("role")
    if not role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role selection required before accessing dashboard."
        )
    db = get_database()
    uid = str(current_user.get("id"))
    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]})
    onb_state = OnboardingService.determine_state(current_user, bus_doc)

    if role == "businessman":
        return DashboardRouteResponse(
            role="businessman",
            dashboard_route="/dashboard/business",
            dashboard_name="Business Dashboard",
            requires_onboarding=onb_state["requires_onboarding"],
            onboarding_completed=onb_state["onboarding_completed"],
            onboarding_status=onb_state["onboarding_status"],
            can_access_dashboard=onb_state["can_access_dashboard"],
            next_step=onb_state["next_step"],
            onboarding_step=onb_state["onboarding_step"],
            online_presence=onb_state["online_presence"],
            onboarding_route=onb_state["onboarding_route"]
        )
    elif role == "influencer":
        return DashboardRouteResponse(
            role="influencer",
            dashboard_route="/dashboard/creator",
            dashboard_name="Influencer/Creator Dashboard",
            requires_onboarding=False,
            onboarding_completed=True,
            onboarding_status="completed",
            can_access_dashboard=True,
            next_step="dashboard",
            onboarding_step=1,
            online_presence=None,
            onboarding_route="/dashboard/creator"
        )
    elif role == "admin":
        return DashboardRouteResponse(
            role="admin",
            dashboard_route="/admin/dashboard",
            dashboard_name="Admin Dashboard",
            requires_onboarding=False,
            onboarding_completed=True,
            onboarding_status="completed",
            can_access_dashboard=True,
            next_step="dashboard",
            onboarding_step=1,
            online_presence=None,
            onboarding_route="/admin/dashboard"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported or unrecognized user role: '{role}'."
        )


@router.get("/dashboard/access")
@router.get("/dashboard/business/protected")
async def verify_dashboard_access(current_user: CurrentUser = Depends(require_completed_onboarding)):
    """
    Protected endpoint for business dashboard access.
    Enforces that onboarding must be completed before accessing dashboard resources.
    Returns 403 if onboarding is incomplete.
    """
    return {
        "success": True,
        "can_access_dashboard": True,
        "role": current_user.get("role"),
        "onboarding_status": "completed",
        "message": "Dashboard access authorized."
    }


@router.get("/dashboard/businessman")
async def get_businessman_dashboard(current_user: CurrentUser = Depends(require_businessman)):
    return {
        "success": True,
        "role": current_user.get("role"),
        "dashboard": "businessman",
        "message": "Welcome to the Businessman Dashboard",
        "user_id": current_user["id"]
    }


@router.get("/dashboard/influencer")
async def get_influencer_dashboard(current_user: CurrentUser = Depends(require_influencer)):
    return {
        "success": True,
        "role": current_user.get("role"),
        "dashboard": "influencer",
        "message": "Welcome to the Influencer/Creator Dashboard",
        "user_id": current_user["id"]
    }

@router.post("/logout")
async def logout(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await AuthService.logout(refresh_token)
    is_live = (
        settings.ENVIRONMENT == "production"
        or (settings.FRONTEND_URL and settings.FRONTEND_URL.startswith("https://"))
        or (settings.BACKEND_URL and settings.BACKEND_URL.startswith("https://"))
    )
    response.delete_cookie(
        key="refresh_token",
        secure=is_live,
        samesite="none" if is_live else "lax"
    )
    return {"success": True, "message": "Logged out successfully"}

@router.post("/refresh")
async def refresh(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return {"success": False, "message": "No refresh token"}
    
    access_token, new_refresh_token = await AuthService.refresh(refresh_token)
    set_refresh_cookie(response, new_refresh_token)
    return {
        "success": True,
        "message": "Token refreshed",
        "data": {"accessToken": access_token}
    }

@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email_get(request: Request, token: str = Query(None), link: str = Query(None)):
    """Handle direct clicks from verification email link in browser. Accepts either ?token=... or ?link=..."""
    accept_header = request.headers.get("accept", "")
    format_param = request.query_params.get("format", "")
    is_json = "application/json" in accept_header or format_param == "json"

    token_or_link = link or token or request.query_params.get("token") or request.query_params.get("link")
    if not token_or_link:
        if is_json:
            return JSONResponse(status_code=400, content={"success": False, "detail": "Missing verification link or token."})
        return HTMLResponse(status_code=400, content="""<!DOCTYPE html><html><body style="font-family: sans-serif; text-align: center; padding: 40px; background: #0f172a; color: white;"><h2>Verification Link Required</h2><p>Please click the full verification link sent to your email.</p></body></html>""")

    try:
        res = await AuthService.verify_email(token_or_link)
        if is_json:
            return JSONResponse({
                "success": True,
                "message": "Email verified successfully" if not res.get("alreadyVerified") else "Email is already verified",
                "data": res
            })

        email = res.get("email", "")
        already = res.get("alreadyVerified", False)
        status_text = "Already Verified" if already else "Email Successfully Verified!"
        msg_text = (
            f"Your email address <strong>{email}</strong> is already verified with your Dhanda Grow account."
            if already else
            f"Your email address <strong>{email}</strong> has been successfully verified. Welcome to <strong>Dhanda Grow</strong>!"
        )

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Email Verification - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      padding: 44px 36px 36px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 5px;
      background: linear-gradient(90deg, #20167c 0%, #4338ca 50%, #f97316 100%);
    }}
    .logo {{
      max-width: 230px;
      width: 100%;
      height: auto;
      margin: 0 auto 28px auto;
      display: block;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.3));
    }}
    .badge {{
      width: 68px;
      height: 68px;
      background: rgba(34, 197, 94, 0.15);
      border: 2px solid #22c55e;
      color: #22c55e;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 34px;
      margin: 0 auto 20px auto;
    }}
    h1 {{
      font-size: 23px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #ffffff;
      letter-spacing: -0.3px;
    }}
    p {{
      color: #94a3b8;
      font-size: 15px;
      line-height: 1.6;
      margin-bottom: 30px;
    }}
    p strong {{
      color: #f1f5f9;
    }}
    .btn {{
      display: inline-block;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 14px 34px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 6px 20px rgba(249, 115, 22, 0.3);
      letter-spacing: 0.3px;
    }}
    .btn:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(249, 115, 22, 0.4);
    }}
    .footer {{
      margin-top: 28px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 18px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">âœ“</div>
    <h1>{status_text}</h1>
    <p>{msg_text}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Proceed to Login</a>
    <div class="footer">Dhanda Grow AI â€¢ Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)

    except HTTPException as e:
        if is_json:
            return JSONResponse(status_code=e.status_code, content={"success": False, "detail": e.detail})

        error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verification Error - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #ef4444;
      padding: 44px 36px 36px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 5px;
      background: #ef4444;
    }}
    .logo {{
      max-width: 230px;
      width: 100%;
      height: auto;
      margin: 0 auto 28px auto;
      display: block;
    }}
    .badge {{
      width: 68px;
      height: 68px;
      background: rgba(239, 68, 68, 0.15);
      border: 2px solid #ef4444;
      color: #ef4444;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 34px;
      margin: 0 auto 20px auto;
    }}
    h1 {{
      font-size: 23px;
      font-weight: 700;
      margin-bottom: 12px;
      color: #ffffff;
    }}
    p {{
      color: #94a3b8;
      font-size: 15px;
      line-height: 1.6;
      margin-bottom: 30px;
    }}
    .btn {{
      display: inline-block;
      background: #334155;
      color: #ffffff;
      text-decoration: none;
      padding: 14px 32px;
      border-radius: 12px;
      font-weight: 600;
      font-size: 15px;
      transition: background 0.2s;
    }}
    .btn:hover {{
      background: #475569;
    }}
    .footer {{
      margin-top: 28px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 18px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">âœ•</div>
    <h1>Verification Failed</h1>
    <p>{e.detail}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Return to Dhanda Grow</a>
    <div class="footer">Dhanda Grow AI â€¢ Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(status_code=e.status_code, content=error_html)

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    """API endpoint to verify email. Accepts either 'link' (full link from email) or 'token'."""
    token_or_link = req.link or req.token
    if not token_or_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'link' (full verification link from email) or 'token'."
        )
    res = await AuthService.verify_email(token_or_link)
    return {
        "success": True,
        "message": "Email verified successfully" if not res.get("alreadyVerified") else "Email is already verified",
        "data": {
            "email": res["email"],
            "emailVerified": True,
            "isVerified": True
        }
    }

@router.post("/resend-verification")
@router.post("/send-verification")
async def resend_verification(req: ResendVerificationRequest):
    """Send/Resend verification link directly to user's Gmail inbox via SMTP."""
    res = await AuthService.resend_verification(req.email, force=bool(req.force))
    is_already = res.get("alreadyVerified", False)
    return {
        "success": True,
        "message": "Email is already verified." if is_already else "Verification link has been sent to your Gmail inbox. Please check your email and tap the link to verify.",
        "data": {
            "email": req.email,
            "emailSent": not is_already,
            "emailVerified": is_already,
            "isVerified": is_already
        }
    }

@router.get("/verification-status")
async def get_verification_status(email: EmailStr = Query(...)):
    """Check if an email is verified or not (returns boolean true/false)."""
    db = get_database()
    clean_email = email.lower().strip()
    user = await db["users"].find_one({"email": clean_email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_verified = bool(user.get("emailVerified", False))
    return {
        "success": True,
        "email": clean_email,
        "emailVerified": is_verified,
        "isVerified": is_verified
    }

@router.post("/verification-status")
async def post_verification_status(req: ResendVerificationRequest):
    """Check if an email is verified or not via JSON body (returns boolean true/false)."""
    db = get_database()
    clean_email = req.email.lower().strip()
    user = await db["users"].find_one({"email": clean_email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_verified = bool(user.get("emailVerified", False))
    return {
        "success": True,
        "email": clean_email,
        "emailVerified": is_verified,
        "isVerified": is_verified
    }


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Send real password reset email via SMTP with Dhanda Grow branding."""
    res = await AuthService.forgot_password(req.email)
    return res

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request, token: str = Query(None), link: str = Query(None)):
    """Handle direct clicks on reset password link in browser. Accepts either ?token=... or ?link=..."""
    raw_val = link or token or request.query_params.get("token") or request.query_params.get("link")
    clean_token = AuthService.extract_token(raw_val)


    # Pre-validate token
    token_valid = True
    user_email = ""
    error_detail = ""

    try:
        payload = jwt.decode(clean_token, settings.JWT_ACCESS_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_email = payload.get("email", "")
    except jwt.ExpiredSignatureError:
        token_valid = False
        error_detail = "This password reset link has expired. Please request a new one."
    except jwt.InvalidTokenError:
        token_valid = False
        error_detail = "This password reset link is invalid or corrupted."

    if not token_valid:
        error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password Expired - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #ef4444;
      padding: 44px 36px;
      border-radius: 22px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; height: 5px;
      background: #ef4444;
    }}
    .logo {{ max-width: 230px; width: 100%; margin: 0 auto 26px auto; display: block; }}
    .badge {{
      width: 68px; height: 68px;
      background: rgba(239, 68, 68, 0.15);
      border: 2px solid #ef4444;
      color: #ef4444;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 34px; margin: 0 auto 20px auto;
    }}
    h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 12px; color: #ffffff; }}
    p {{ color: #94a3b8; font-size: 15px; line-height: 1.6; margin-bottom: 28px; }}
    .btn {{
      display: inline-block;
      background: #334155; color: #ffffff;
      text-decoration: none; padding: 13px 30px;
      border-radius: 12px; font-weight: 600; font-size: 14px;
    }}
    .footer {{ margin-top: 26px; font-size: 12px; color: #64748b; border-top: 1px solid #334155; padding-top: 18px; }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    <div class="badge">âœ•</div>
    <h1>Link Expired or Invalid</h1>
    <p>{error_detail}</p>
    <a href="{settings.FRONTEND_URL}/login" class="btn">Return to Dhanda Grow</a>
    <div class="footer">Dhanda Grow AI â€¢ Apne Business Ko Banao Smart &amp; Digital</div>
  </div>
</body>
</html>"""
        return HTMLResponse(status_code=400, content=error_html)

    form_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password - Dhanda Grow</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, #0f172a 100%);
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      padding: 40px 36px;
      border-radius: 22px;
      max-width: 460px;
      width: 100%;
      text-align: center;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.6);
      position: relative;
      overflow: hidden;
    }}
    .card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; height: 5px;
      background: linear-gradient(90deg, #20167c 0%, #4338ca 50%, #f97316 100%);
    }}
    .logo {{
      max-width: 220px;
      width: 100%;
      height: auto;
      margin: 0 auto 22px auto;
      display: block;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.3));
    }}
    h1 {{
      font-size: 22px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #ffffff;
      letter-spacing: -0.3px;
    }}
    .subtitle {{
      color: #94a3b8;
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: 26px;
    }}
    .form-group {{
      text-align: left;
      margin-bottom: 18px;
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 13px 16px;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 10px;
      color: #f8fafc;
      font-size: 15px;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }}
    input:focus {{
      border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }}
    .error-msg {{
      color: #f87171;
      font-size: 13px;
      margin-bottom: 16px;
      display: none;
      text-align: center;
      background: rgba(239, 68, 68, 0.12);
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }}
    .btn {{
      width: 100%;
      margin-top: 8px;
      padding: 14px;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      border: none;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 6px 20px rgba(249, 115, 22, 0.3);
    }}
    .btn:hover {{
      transform: translateY(-1px);
      box-shadow: 0 8px 24px rgba(249, 115, 22, 0.4);
    }}
    .btn:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }}
    .success-container {{
      display: none;
    }}
    .badge {{
      width: 68px; height: 68px;
      background: rgba(34, 197, 94, 0.15);
      border: 2px solid #22c55e;
      color: #22c55e;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 34px; margin: 0 auto 20px auto;
    }}
    .login-btn {{
      display: inline-block;
      margin-top: 20px;
      background: linear-gradient(135deg, #20167c 0%, #4338ca 50%, #f97316 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 13px 34px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 15px;
    }}
    .footer {{
      margin-top: 26px;
      font-size: 12px;
      color: #64748b;
      border-top: 1px solid #334155;
      padding-top: 16px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <img src="/assets/images/dhandagrow.png" alt="Dhanda Grow AI" class="logo" onerror="this.style.display='none'" />
    
    <div id="formSection">
      <h1>Set New Password</h1>
      <p class="subtitle">Enter your new password and confirm it below</p>
      
      <div id="errorBox" class="error-msg"></div>

      <form id="resetForm" onsubmit="handleSubmit(event)">
        <div class="form-group">
          <label for="newPassword">New Password</label>
          <input type="password" id="newPassword" placeholder="Minimum 6 characters" required autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label for="confirmPassword">Confirm Password</label>
          <input type="password" id="confirmPassword" placeholder="Re-enter new password" required autocomplete="new-password" />
        </div>
        <button type="submit" id="submitBtn" class="btn">Update Password</button>
      </form>
    </div>

    <div id="successSection" class="success-container">
      <div class="badge">âœ“</div>
      <h1>Password Reset Successful!</h1>
      <p style="color: #94a3b8; font-size: 15px; line-height: 1.6; margin-top: 10px;">
        Your password has been updated successfully. You can now log in to Dhanda Grow using your new credentials.
      </p>
      <a href="{settings.FRONTEND_URL}/login" class="login-btn">Proceed to Login</a>
    </div>

    <div class="footer">Dhanda Grow AI â€¢ Apne Business Ko Banao Smart &amp; Digital</div>
  </div>

  <script>
    async function handleSubmit(e) {{
      e.preventDefault();
      const newPassword = document.getElementById('newPassword').value;
      const confirmPassword = document.getElementById('confirmPassword').value;
      const errorBox = document.getElementById('errorBox');
      const submitBtn = document.getElementById('submitBtn');

      errorBox.style.display = 'none';

      if (newPassword.length < 6) {{
        errorBox.textContent = 'Password must be at least 6 characters long.';
        errorBox.style.display = 'block';
        return;
      }}

      if (newPassword !== confirmPassword) {{
        errorBox.textContent = 'Passwords do not match.';
        errorBox.style.display = 'block';
        return;
      }}

      submitBtn.disabled = true;
      submitBtn.textContent = 'Updating password...';

      try {{
        const response = await fetch('/api/v1/auth/reset-password', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }},
          body: JSON.stringify({{
            token: '{clean_token}',
            newPassword: newPassword,
            confirmPassword: confirmPassword
          }})
        }});

        const result = await response.json();

        if (response.ok) {{
          document.getElementById('formSection').style.display = 'none';
          document.getElementById('successSection').style.display = 'block';
        }} else {{
          errorBox.textContent = result.detail || result.message || 'Failed to reset password.';
          errorBox.style.display = 'block';
          submitBtn.disabled = false;
          submitBtn.textContent = 'Update Password';
        }}
      }} catch (err) {{
        errorBox.textContent = 'Connection error. Please try again.';
        errorBox.style.display = 'block';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Update Password';
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=form_html)

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """API endpoint to reset password. Accepts either 'link' (full reset link from email) or 'token'."""
    token_or_link = req.link or req.token
    if not token_or_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'link' (full reset link from email) or 'token'."
        )
    res = await AuthService.reset_password(token_or_link, req.newPassword, req.confirmPassword)
    return res




from app.services.google_service import GoogleService
from app.schemas.auth import GoogleAuthLoginRequest

@router.get("/google/connect")
async def google_connect(redirect_uri: Optional[str] = Query(None)):
    """Returns Google OAuth authorization URL."""
    auth_url = GoogleService.get_authorization_url(redirect_uri=redirect_uri)
    return {"success": True, "authorization_url": auth_url, "url": auth_url}

@router.post("/google/login")
async def google_login(req: GoogleAuthLoginRequest, response: Response, request: Request = None):
    """Authenticate existing user via Google OAuth 2.0 (or register if mode='signup')."""
    db = get_database()
    if not req.code and not req.access_token and not req.id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide 'code', 'access_token', or 'id_token'."
        )

    path_mode = "signup" if (request and "signup" in str(request.url.path)) else "login"
    mode = (req.mode or path_mode).lower().strip()
    redirect_uri = req.redirect_uri or req.redirectUri
    account_type = req.accountType or req.account_type or "business"
    raw_phone = req.phone_number or req.phone or req.mobile
    country_code = req.country_code or req.countryCode
    phone_verification_token = req.phone_verification_token or req.verification_token
    user, access_token_jwt, refresh_token_jwt = await GoogleService.authenticate_google_user(
        db=db,
        code=req.code,
        access_token=req.access_token,
        id_token=req.id_token,
        redirect_uri=redirect_uri,
        account_type=account_type,
        mode=mode,
        phone_number=raw_phone,
        country_code=country_code,
        phone_verification_token=phone_verification_token,
    )

    if request and "signup" in str(request.url.path) and response:
        response.status_code = status.HTTP_201_CREATED

    set_refresh_cookie(response, refresh_token_jwt)

    role = getattr(user, "role", None)
    requires_role = role is None or role in ["user", ""]
    dashboard_route = "/select-role" if requires_role else ("/influencer" if role == "influencer" else "/dashboard")
    user_phone = getattr(user, "phone_number", None) or getattr(user, "phone", None)
    phone_verified = getattr(user, "phone_verified", False)

    user_payload = {
        "id": str(user.id),
        "fullName": getattr(user, "fullName", None) or getattr(user, "name", "User"),
        "name": getattr(user, "name", None) or getattr(user, "fullName", "User"),
        "firstName": getattr(user, "firstName", None),
        "lastName": getattr(user, "lastName", None),
        "email": getattr(user, "email", None),
        "phone": user_phone,
        "phone_number": user_phone,
        "contactNumber": user_phone,
        "phone_verified": phone_verified,
        "accountType": getattr(user, "accountType", "business"),
        "role": role,
        "emailVerified": bool(getattr(user, "emailVerified", True)),
        "email_verified": bool(getattr(user, "email_verified", True)),
        "isVerified": bool(getattr(user, "email_verified", True)),
        "profileImageUrl": getattr(user, "profileImageUrl", None),
        "onboardingCompleted": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_completed": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_step": getattr(user, "onboarding_step", 1) or 1,
    }

    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user.id)}, {"ownerId": str(user.id)}]})
    u_dict = user.model_dump() if hasattr(user, "model_dump") else (user.dict() if hasattr(user, "dict") else dict(user))
    onb_state = OnboardingService.determine_state(u_dict, bus_doc)

    onboarding_completed = onb_state["onboarding_completed"]
    requires_role = onb_state["requires_role_selection"]
    is_existing = (not requires_role) and onboarding_completed
    next_step = onb_state["next_step"]

    user_payload["online_presence"] = onb_state.get("online_presence")
    user_payload["onboarding_status"] = onb_state["onboarding_status"]
    user_payload["onboarding_step"] = onb_state["onboarding_step"]
    user_payload["onboardingCompleted"] = onboarding_completed
    user_payload["onboarding_completed"] = onboarding_completed
    user_payload["can_access_dashboard"] = onb_state["can_access_dashboard"]
    user_payload["next_step"] = next_step

    return {
        "success": True,
        "message": "Google login successful" if mode == "login" else "Google registration successful",
        "exists": is_existing,
        "is_existing_user": is_existing,
        "user_exists": is_existing,
        "next_step": next_step,
        "access_token": access_token_jwt,
        "accessToken": access_token_jwt,
        "token": access_token_jwt,
        "role": role,
        "requires_role_selection": requires_role,
        "dashboard_route": dashboard_route,
        "onboarding_status": onb_state["onboarding_status"],
        "onboarding_step": onb_state["onboarding_step"],
        "online_presence": onb_state.get("online_presence"),
        "onboardingCompleted": onboarding_completed,
        "onboarding_completed": onboarding_completed,
        "can_access_dashboard": onb_state["can_access_dashboard"],
        "user": user_payload,
        "data": {
            "access_token": access_token_jwt,
            "accessToken": access_token_jwt,
            "token": access_token_jwt,
            "role": role,
            "requires_role_selection": requires_role,
            "dashboard_route": dashboard_route,
            "onboarding_status": onb_state["onboarding_status"],
            "onboarding_step": onb_state["onboarding_step"],
            "online_presence": onb_state.get("online_presence"),
            "onboardingCompleted": onboarding_completed,
            "onboarding_completed": onboarding_completed,
            "can_access_dashboard": onb_state["can_access_dashboard"],
            "next_step": next_step,
            "user": user_payload
        }
    }


@router.post("/google/signup", status_code=status.HTTP_201_CREATED)
async def google_signup(req: GoogleAuthLoginRequest, response: Response, request: Request = None):
    """Register new user via Google OAuth 2.0."""
    req.mode = "signup"
    if response:
        response.status_code = status.HTTP_201_CREATED
    return await google_login(req=req, response=response, request=request)

@router.get("/google/callback")
async def google_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Direct callback handler for Google OAuth redirect."""
    from fastapi.responses import RedirectResponse
    frontend_base = settings.FRONTEND_URL or "http://localhost:3000"
    if error:
        return RedirectResponse(url=f"{frontend_base}/login/user?error={error}")
    if code:
        state_param = f"&state={state}" if state else ""
        return RedirectResponse(url=f"{frontend_base}/login/user?code={code}&provider=google{state_param}")
    return RedirectResponse(url=f"{frontend_base}/login/user")


@router.post("/facebook/signup", status_code=status.HTTP_201_CREATED)
async def facebook_signup(req: FacebookAuthLoginRequest, response: Response):
    """Register user using Facebook Login."""
    req.mode = "signup"
    return await facebook_login(req, response)

from app.services.instagram_service import InstagramService

@router.post("/instagram/login")
async def instagram_login(req: InstagramAuthLoginRequest, response: Response):
    """Authenticate or register user using Instagram Login."""
    db = get_database()
    access_token = req.access_token

    if not access_token and req.code:
        token_data = await InstagramService.exchange_code_for_token(req.code)
        access_token = token_data.get("access_token")

    if not access_token:
        # Fallback for dev/demo or missing token
        access_token = "DEMO_IG_ACCESS_TOKEN"

    user, access_token_jwt, refresh_token_jwt = await InstagramService.authenticate_instagram_user(
        db=db,
        access_token=access_token,
        account_type=req.accountType or "business",
    )
    set_refresh_cookie(response, refresh_token_jwt)

    user_payload = {
        "id": str(user.id),
        "fullName": user.fullName,
        "firstName": user.firstName,
        "lastName": user.lastName,
        "email": user.email,
        "phone": user.phone,
        "contactNumber": user.contactNumber,
        "accountType": user.accountType,
        "role": getattr(user, "role", "user") or "user",
        "name": getattr(user, "name", user.fullName) or user.fullName,
        "emailVerified": bool(user.emailVerified),
        "email_verified": bool(user.emailVerified),
        "isVerified": bool(user.emailVerified),
        "profileImageUrl": user.profileImageUrl,
        "onboardingCompleted": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_completed": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_step": getattr(user, "onboarding_step", 1) or 1,
    }

    return {
        "success": True,
        "message": "Instagram login successful",
        "access_token": access_token_jwt,
        "accessToken": access_token_jwt,
        "token": access_token_jwt,
        "user": user_payload,
        "data": {
            "access_token": access_token_jwt,
            "accessToken": access_token_jwt,
            "token": access_token_jwt,
            "user": user_payload
        }
    }

@router.post("/instagram/signup", status_code=status.HTTP_201_CREATED)
async def instagram_signup(req: InstagramAuthLoginRequest, response: Response):
    """Explicitly register a new user via Instagram Login."""
    req.mode = "signup"
    return await instagram_login(req, response)


from app.services.linkedin_service import LinkedInService

@router.get("/linkedin/connect")
async def linkedin_connect(
    redirect_uri: Optional[str] = Query(None),
    mode: str = Query("login")
):
    """Returns LinkedIn OAuth 2.0 authorization URL."""
    auth_url = LinkedInService.get_authorization_url(redirect_uri=redirect_uri, mode=mode)
    return {"success": True, "authorization_url": auth_url, "url": auth_url}


@router.post("/linkedin/login")
async def linkedin_login(req: LinkedInAuthLoginRequest, response: Response):
    """Authenticate or register user via LinkedIn OAuth."""
    db = get_database()
    if not req.code and not req.access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide 'code' or 'access_token'."
        )

    path_mode = "signup" if (request and "signup" in str(request.url.path)) else "login"
    mode = (req.mode or path_mode).lower().strip()
    user, access_token_jwt, refresh_token_jwt = await LinkedInService.authenticate_linkedin_user(
        db=db,
        code=req.code,
        access_token=req.access_token,
        id_token=getattr(req, "id_token", None),
        redirect_uri=req.redirect_uri,
        account_type=req.accountType or "business",
        mode=mode,
    )
    set_refresh_cookie(response, refresh_token_jwt)

    user_payload = {
        "id": str(user.id),
        "fullName": user.fullName,
        "firstName": user.firstName,
        "lastName": user.lastName,
        "email": user.email,
        "phone": user.phone,
        "contactNumber": user.contactNumber,
        "accountType": user.accountType,
        "role": getattr(user, "role", "user") or "user",
        "name": getattr(user, "name", user.fullName) or user.fullName,
        "emailVerified": bool(user.emailVerified),
        "email_verified": bool(user.emailVerified),
        "isVerified": bool(user.emailVerified),
        "profileImageUrl": user.profileImageUrl,
        "onboardingCompleted": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_completed": bool(getattr(user, "onboardingCompleted", False)),
        "onboarding_step": getattr(user, "onboarding_step", 1) or 1,
    }

    return {
        "success": True,
        "message": "LinkedIn authentication successful",
        "access_token": access_token_jwt,
        "accessToken": access_token_jwt,
        "token": access_token_jwt,
        "user": user_payload,
        "data": {
            "access_token": access_token_jwt,
            "accessToken": access_token_jwt,
            "token": access_token_jwt,
            "user": user_payload
        }
    }


@router.post("/linkedin/signup", status_code=status.HTTP_201_CREATED)
async def linkedin_signup(req: LinkedInAuthLoginRequest, response: Response):
    """Register user using LinkedIn Login."""
    req.mode = "signup"
    return await linkedin_login(req, response)


@router.get("/linkedin/callback")
async def linkedin_callback(
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Direct callback handler for LinkedIn OAuth redirect."""
    from fastapi.responses import RedirectResponse
    frontend_base = settings.FRONTEND_URL or "http://localhost:3000"
    if error or error_description:
        err_msg = error_description or error
        return RedirectResponse(url=f"{frontend_base}/login/user?error={urllib.parse.quote(str(err_msg))}")

    if code:
        state_param = f"&state={state}" if state else ""
        
        # Calculate the exact callback URL that received this request
        base_url = str(request.base_url).rstrip("/")
        proto = request.headers.get("x-forwarded-proto")
        if proto:
            host = request.headers.get("x-forwarded-host") or request.url.netloc
            base_url = f"{proto}://{host}"
        elif request.headers.get("host") and "ngrok" in request.headers.get("host", ""):
            base_url = f"https://{request.headers.get('host')}"
            
        current_redirect_uri = f"{base_url}{request.url.path}"
        
        # Attempt direct token exchange & login on backend
        try:
            db = get_database()
            mode = "signup" if (state and "signup" in state) else "login"
            user, access_token_jwt, refresh_token_jwt = await LinkedInService.authenticate_linkedin_user(
                db=db,
                code=code,
                redirect_uri=current_redirect_uri,
                account_type="business",
                mode=mode,
            )
            redirect_resp = RedirectResponse(
                url=f"{frontend_base}/login/user?token={access_token_jwt}&provider=linkedin{state_param}",
                status_code=status.HTTP_302_FOUND,
            )
            set_refresh_cookie(redirect_resp, refresh_token_jwt)
            return redirect_resp
        except Exception as e:
            logger.warning(f"Direct LinkedIn callback exchange failed, redirecting code to frontend: {e}")
            return RedirectResponse(url=f"{frontend_base}/login/user?code={code}&provider=linkedin{state_param}")

    return RedirectResponse(url=f"{frontend_base}/login/user")



@router.get("/linkedin/status")
async def linkedin_status(current_user=Depends(get_current_user)):
    db = get_database()
    uid = str(current_user.get("id") or current_user.get("_id"))
    user_oid = ObjectId(uid) if ObjectId.is_valid(uid) else uid
    
    user_doc = await db["users"].find_one({"_id": user_oid}) if ObjectId.is_valid(uid) else None
    biz_doc = await db["businesses"].find_one({
        "$or": [
            {"ownerId": uid},
            {"ownerId": user_oid},
            {"userId": uid},
            {"userId": user_oid},
        ]
    })
    conn = await db["linkedin_connections"].find_one({"user_id": uid})
    if not conn and user_doc and user_doc.get("email"):
        conn = await db["linkedin_connections"].find_one({"email": user_doc["email"]})
        
    author_id = (
        (biz_doc and biz_doc.get("linkedin_author_id")) or
        (user_doc and user_doc.get("linkedin_author_id")) or
        (conn and conn.get("author_id")) or
        ""
    )
    access_token = (
        (biz_doc and biz_doc.get("linkedin_access_token")) or
        (user_doc and user_doc.get("linkedin_access_token")) or
        (conn and conn.get("access_token")) or
        ""
    )
    connected = bool(
        (biz_doc and biz_doc.get("linkedin_connected")) or
        (user_doc and user_doc.get("linkedin_connected")) or
        (conn and conn.get("connected")) or
        (author_id and access_token)
    )
    return {
        "success": True,
        "connected": connected,
        "linkedin_connected": connected,
        "author_id": author_id,
        "linkedin_author_id": author_id,
        "has_token": bool(access_token),
        "access_token": access_token if access_token else "",
        "linkedin_access_token": access_token if access_token else "",
    }


@router.post("/linkedin/save-credentials")
async def linkedin_save_credentials(req: dict, current_user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    db = get_database()
    uid = str(current_user.get("id") or current_user.get("_id"))
    user_oid = ObjectId(uid) if ObjectId.is_valid(uid) else uid
    
    author_id = (req.get("author_id") or req.get("linkedin_author_id") or "").strip()
    access_token = (req.get("access_token") or req.get("linkedin_access_token") or "").strip()
    connected = req.get("connected", bool(author_id and access_token))
    
    # 1. Update users
    if ObjectId.is_valid(uid):
        user_set = {
            "linkedin_author_id": author_id,
            "linkedin_access_token": access_token,
            "linkedin_connected": connected,
            "updated_at": now,
        }
        if author_id:
            li_id = author_id.replace("urn:li:person:", "")
            user_set["linkedinId"] = li_id
            user_set["linkedin_id"] = li_id
        await db["users"].update_one({"_id": user_oid}, {"$set": user_set})
        
    # 2. Update businesses
    biz_query = {
        "$or": [
            {"owner_id": uid},
            {"owner_id": user_oid},
            {"ownerId": uid},
            {"ownerId": user_oid},
            {"user_id": uid},
            {"user_id": user_oid},
            {"userId": uid},
            {"userId": user_oid},
        ]
    }
    await db["businesses"].update_one(
        biz_query,
        {
            "$set": {
                "owner_id": uid,
                "ownerId": uid,
                "user_id": uid,
                "linkedin_author_id": author_id,
                "linkedin_access_token": access_token,
                "linkedin_connected": connected,
                "updated_at": now,
            },
            "$setOnInsert": {
                "businessName": "My Business",
                "business_name": "My Business",
                "businessType": "Retail",
                "industry": "General",
                "created_at": now,
            }
        },
        upsert=True
    )
    
    # 3. Update linkedin_connections
    if author_id or access_token:
        await db["linkedin_connections"].update_one(
            {"user_id": uid},
            {"$set": {
                "user_id": uid,
                "platform": "linkedin",
                "author_id": author_id,
                "access_token": access_token,
                "connected": connected,
                "updated_at": now,
            }},
            upsert=True
        )
    else:
        await db["linkedin_connections"].delete_one({"user_id": uid})
        
    return {
        "success": True,
        "message": "LinkedIn credentials saved successfully",
        "author_id": author_id,
        "connected": connected,
    }


@router.post("/linkedin/disconnect")
async def linkedin_disconnect(current_user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    db = get_database()
    uid = str(current_user.get("id") or current_user.get("_id"))
    user_oid = ObjectId(uid) if ObjectId.is_valid(uid) else uid
    
    if ObjectId.is_valid(uid):
        await db["users"].update_one(
            {"_id": user_oid},
            {"$set": {
                "linkedin_author_id": "",
                "linkedin_access_token": "",
                "linkedin_connected": False,
                "updated_at": now,
            }}
        )
    await db["businesses"].update_many(
        {"$or": [{"ownerId": uid}, {"ownerId": user_oid}, {"userId": uid}, {"userId": user_oid}]},
        {"$set": {
            "linkedin_author_id": "",
            "linkedin_access_token": "",
            "linkedin_connected": False,
            "updated_at": now,
        }}
    )
    await db["linkedin_connections"].delete_one({"user_id": uid})
    return {"success": True, "message": "LinkedIn disconnected successfully"}
