from fastapi import APIRouter, Depends, status, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    OTPVerifyRequest,
    OTPResendRequest,
    RoleSelectRequest,
    RoleSelectResponse,
    DashboardRouteResponse
)
from app.services.auth_service import (
    AuthService,
    PhoneNotVerifiedException
)
from app.core.security import (
    create_access_token,
    get_current_user,
    CurrentUser,
    require_businessman,
    require_influencer
)

router = APIRouter()

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(user_in: UserCreate):
    result = await AuthService.handle_signup(user_in)
    return result

@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(request: OTPVerifyRequest):
    identifier = request.phone_number or request.phone or request.mobile or (str(request.email) if request.email else None)
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number or identifier is required for OTP verification."
        )

    user = await AuthService.verify_otp(identifier, request.otp)
    access_token = create_access_token(subject=str(user.id))

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            phone_number=getattr(user, "phone_number", None),
            phone_verified=getattr(user, "phone_verified", False),
            email=getattr(user, "email", None),
            role=getattr(user, "role", None),
            email_verified=getattr(user, "email_verified", True)
        )
    )

@router.post("/resend-otp")
async def resend_otp(request: OTPResendRequest):
    identifier = request.phone_number or request.phone or request.mobile or (str(request.email) if request.email else None)
    if not identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number or identifier is required to resend OTP."
        )

    result = await AuthService.resend_otp(identifier)
    return result

@router.post("/login", response_model=TokenResponse)
async def login(user_in: UserLogin):
    try:
        user = await AuthService.authenticate_user(user_in)
    except PhoneNotVerifiedException as e:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(e), "code": "PHONE_NOT_VERIFIED"}
        )

    access_token = create_access_token(subject=str(user.id))

    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            phone_number=getattr(user, "phone_number", None),
            phone_verified=getattr(user, "phone_verified", False),
            email=getattr(user, "email", None),
            role=getattr(user, "role", None),
            email_verified=getattr(user, "email_verified", True)
        )
    )

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

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        name=current_user["name"],
        phone_number=current_user.get("phone_number"),
        phone_verified=current_user.get("phone_verified", False),
        email=current_user.get("email") or None,
        role=current_user.get("role"),
        email_verified=current_user.get("email_verified", True)
    )

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

    user_resp = UserResponse(
        id=str(updated_user.id),
        name=updated_user.name,
        phone_number=getattr(updated_user, "phone_number", None),
        phone_verified=getattr(updated_user, "phone_verified", False),
        email=getattr(updated_user, "email", None),
        role=getattr(updated_user, "role", None),
        email_verified=getattr(updated_user, "email_verified", True)
    )

    return RoleSelectResponse(
        id=user_resp.id,
        name=user_resp.name,
        phone_number=user_resp.phone_number,
        phone_verified=user_resp.phone_verified,
        email=user_resp.email,
        role=user_resp.role,
        email_verified=user_resp.email_verified,
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
    if role == "businessman":
        return DashboardRouteResponse(
            role="businessman",
            dashboard_route="/dashboard/business",
            dashboard_name="Business Dashboard"
        )
    elif role == "influencer":
        return DashboardRouteResponse(
            role="influencer",
            dashboard_route="/dashboard/creator",
            dashboard_name="Influencer/Creator Dashboard"
        )
    elif role == "admin":
        return DashboardRouteResponse(
            role="admin",
            dashboard_route="/admin/dashboard",
            dashboard_name="Admin Dashboard"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported or unrecognized user role: '{role}'."
        )

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

