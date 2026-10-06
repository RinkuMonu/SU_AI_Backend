from fastapi import APIRouter, Depends, status, Request
from fastapi.responses import JSONResponse
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse, OTPVerifyRequest, OTPResendRequest
from app.services.auth_service import AuthService, EmailNotVerifiedException
from app.core.security import create_access_token, get_current_user, CurrentUser
from app.models.user import User

router = APIRouter()

@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def signup(user_in: UserCreate):
    user = await AuthService.handle_signup(user_in)
    access_token = create_access_token(subject=str(user.id))
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            email=user.email,
            role=getattr(user, "role", "user"),
            email_verified=True
        )
    )

@router.post("/login", response_model=TokenResponse)
async def login(user_in: UserLogin):
    try:
        user = await AuthService.authenticate_user(user_in)
    except EmailNotVerifiedException as e:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(e), "code": "EMAIL_NOT_VERIFIED"}
        )
    
    access_token = create_access_token(subject=str(user.id))
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            email=user.email,
            role=getattr(user, "role", "user"),
            email_verified=getattr(user, "email_verified", True)
        )
    )

from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from fastapi import HTTPException

@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        user_in = UserLogin(email=form_data.username, password=form_data.password)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format. Please enter a valid email address in the Username field."
        )
    try:
        user = await AuthService.authenticate_user(user_in)
    except EmailNotVerifiedException as e:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(e), "code": "EMAIL_NOT_VERIFIED"}
        )
    
    access_token = create_access_token(subject=str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        name=current_user["name"],
        email=current_user["email"],
        role=current_user["role"],
        email_verified=current_user.get("email_verified", True)
    )
