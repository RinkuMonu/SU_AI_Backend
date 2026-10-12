import os

config_content = """
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    NODE_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"
    PORT: int = 8000

    MONGO_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "sevenunique_ai_db"

    JWT_ACCESS_SECRET: str = "development_access_secret"
    JWT_REFRESH_SECRET: str = "development_refresh_secret"
    TOKEN_ENCRYPTION_KEY: str = "development_encryption_key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Email config
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str = "noreply@example.com"
    
    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
"""

auth_service_content = """
from fastapi import HTTPException, status, Response
from app.core.database import get_database
from app.models.user import User
from app.models.refresh_session import RefreshSession
from app.schemas.auth import SignupRequest, LoginRequest
from app.core.security import get_password_hash, verify_password, create_access_token
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import jwt
import os
import random
import string
from app.core.config import settings

class AuthService:
    @staticmethod
    async def signup(req: SignupRequest) -> User:
        db = get_database()
        email = req.email.lower().strip()
        existing = await db["users"].find_one({"email": email})
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
        
        user = User(
            fullName=req.fullName,
            email=email,
            hashed_password=get_password_hash(req.password),
            accountType=req.accountType,
            termsAcceptedAt=datetime.now(timezone.utc) if req.termsAccepted else None
        )
        doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await db["users"].insert_one(doc)
        user.id = str(result.inserted_id)
        
        # In a real app we'd send an email verification token here
        return user

    @staticmethod
    async def login(req: LoginRequest):
        db = get_database()
        email = req.email.lower().strip()
        doc = await db["users"].find_one({"email": email})
        if not doc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        
        user = User(**doc)
        if not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
            
        access_token = AuthService.create_token(user.id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
        refresh_token = AuthService.create_token(user.id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
        
        # Save refresh session
        rs = RefreshSession(
            userId=user.id,
            hashedToken=get_password_hash(refresh_token),
            expiresAt=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        await db["refresh_sessions"].insert_one(rs.model_dump(by_alias=True, exclude={"id"}))
        
        return user, access_token, refresh_token

    @staticmethod
    async def logout(refresh_token: str):
        if not refresh_token:
            return
        db = get_database()
        try:
            payload = jwt.decode(refresh_token, settings.JWT_REFRESH_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                # Invalidate all sessions for simplicity, or just this one if we compare hashes
                await db["refresh_sessions"].update_many(
                    {"userId": user_id, "isRevoked": False},
                    {"$set": {"isRevoked": True}}
                )
        except jwt.InvalidTokenError:
            pass

    @staticmethod
    async def refresh(refresh_token: str):
        db = get_database()
        try:
            payload = jwt.decode(refresh_token, settings.JWT_REFRESH_SECRET, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            # Check if token is in db and not revoked
            sessions = await db["refresh_sessions"].find({"userId": user_id, "isRevoked": False, "expiresAt": {"$gt": datetime.now(timezone.utc)}}).to_list(length=None)
            valid_session = None
            for s in sessions:
                if verify_password(refresh_token, s["hashedToken"]):
                    valid_session = s
                    break
                    
            if not valid_session:
                raise HTTPException(status_code=401, detail="Session revoked or invalid")
                
            # Rotate refresh token
            await db["refresh_sessions"].update_one({"_id": valid_session["_id"]}, {"$set": {"isRevoked": True}})
            
            access_token = AuthService.create_token(user_id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
            new_refresh_token = AuthService.create_token(user_id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
            
            new_rs = RefreshSession(
                userId=user_id,
                hashedToken=get_password_hash(new_refresh_token),
                expiresAt=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
            )
            await db["refresh_sessions"].insert_one(new_rs.model_dump(by_alias=True, exclude={"id"}))
            
            return access_token, new_refresh_token
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    @staticmethod
    def create_token(subject: str, secret: str, expires_delta: timedelta) -> str:
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode = {"exp": expire, "sub": str(subject)}
        return jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)
"""

security_update_content = """
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from typing import Optional, Union, Any

from app.core.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_ACCESS_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    try:
        decoded_token = jwt.decode(token, settings.JWT_ACCESS_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return decoded_token
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from app.models.user import User

class CurrentUser(dict):
    def __getattr__(self, attr):
        if attr in self:
            return self[attr]
        raise AttributeError(f"'CurrentUser' object has no attribute '{attr}'")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

def get_token_from_header_or_cookie(request: Request) -> str:
    # Check header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    
    # Check cookie (if some implementations prefer access token in cookie, but usually it's refresh)
    # The prompt says refresh token in HTTP-only cookie.
    raise HTTPException(status_code=401, detail="Not authenticated")

async def get_current_user(request: Request) -> CurrentUser:
    from app.core.database import get_database
    db = get_database()
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise credentials_exception
        
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
        
    user_id: str = payload.get("sub")
    if user_id is None or not ObjectId.is_valid(user_id):
        raise credentials_exception
        
    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if user_doc is None:
        raise credentials_exception
        
    return CurrentUser({
        "id": str(user_doc["_id"]),
        "fullName": user_doc.get("fullName", "Unknown"),
        "email": user_doc.get("email", ""),
        "accountType": user_doc.get("accountType", "personal"),
        "emailVerified": user_doc.get("emailVerified", False),
    })
"""

auth_endpoints_content = """
from fastapi import APIRouter, Depends, status, Request, Response
from app.schemas.auth import SignupRequest, LoginRequest, VerifyEmailRequest, ResendVerificationRequest, ForgotPasswordRequest, ResetPasswordRequest
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.core.config import settings

router = APIRouter()

def set_refresh_cookie(response: Response, refresh_token: str):
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax" if settings.ENVIRONMENT == "development" else "none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )

@router.post("/signup")
async def signup(req: SignupRequest):
    user = await AuthService.signup(req)
    return {
        "success": True,
        "message": "User registered successfully",
        "data": {"userId": user.id}
    }

@router.post("/login")
async def login(req: LoginRequest, response: Response):
    user, access_token, refresh_token = await AuthService.login(req)
    set_refresh_cookie(response, refresh_token)
    return {
        "success": True,
        "message": "Logged in successfully",
        "data": {
            "accessToken": access_token,
            "user": {
                "id": user.id,
                "fullName": user.fullName,
                "email": user.email,
                "accountType": user.accountType
            }
        }
    }

@router.post("/logout")
async def logout(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await AuthService.logout(refresh_token)
    response.delete_cookie("refresh_token")
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

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    return {"success": True, "message": "Email verified successfully (Mocked)"}

@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest):
    return {"success": True, "message": "Verification email sent (Mocked)"}

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    return {"success": True, "message": "Password reset email sent (Mocked)"}

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    return {"success": True, "message": "Password reset successfully (Mocked)"}
"""

users_endpoints_content = """
from fastapi import APIRouter, Depends, status, HTTPException
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.schemas.user import UserResponse, UserPreferencesUpdate, UserUpdate
from bson import ObjectId

router = APIRouter()

@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    doc = await db["users"].find_one({"_id": ObjectId(current_user["id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
        
    doc["id"] = str(doc["_id"])
    return {
        "success": True,
        "data": doc
    }

@router.patch("/me")
async def update_me(req: UserUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        await db["users"].update_one(
            {"_id": ObjectId(current_user["id"])},
            {"$set": update_data}
        )
    
    doc = await db["users"].find_one({"_id": ObjectId(current_user["id"])})
    doc["id"] = str(doc["_id"])
    return {
        "success": True,
        "message": "User updated successfully",
        "data": doc
    }

@router.patch("/me/preferences")
async def update_preferences(req: UserPreferencesUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        await db["users"].update_one(
            {"_id": ObjectId(current_user["id"])},
            {"$set": update_data}
        )
    
    return {
        "success": True,
        "message": "Preferences updated successfully"
    }
"""

businesses_endpoints_content = """
from fastapi import APIRouter, Depends, status, HTTPException
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.schemas.business import BusinessCreate, BusinessUpdate, BusinessResponse
from app.models.business import Business
from bson import ObjectId

router = APIRouter()

@router.post("/")
async def create_business(req: BusinessCreate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    if current_user["accountType"] != "business":
        raise HTTPException(status_code=403, detail="Personal users cannot create business profiles")
        
    existing = await db["businesses"].find_one({"ownerId": current_user["id"]})
    if existing:
        raise HTTPException(status_code=409, detail="Business profile already exists for this user")
        
    business = Business(
        ownerId=current_user["id"],
        **req.model_dump()
    )
    doc = business.model_dump(by_alias=True, exclude={"id"})
    res = await db["businesses"].insert_one(doc)
    doc["id"] = str(res.inserted_id)
    return {
        "success": True,
        "message": "Business created successfully",
        "data": doc
    }

@router.get("/")
async def get_businesses(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    docs = await db["businesses"].find({"ownerId": current_user["id"]}).to_list(length=100)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {
        "success": True,
        "data": docs
    }

@router.get("/{id}")
async def get_business(id: str, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    doc = await db["businesses"].find_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Business not found")
    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "data": doc
    }

@router.patch("/{id}")
async def update_business(id: str, req: BusinessUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    doc = await db["businesses"].find_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Business not found")
        
    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        await db["businesses"].update_one(
            {"_id": ObjectId(id)},
            {"$set": update_data}
        )
    
    doc = await db["businesses"].find_one({"_id": ObjectId(id)})
    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "message": "Business updated successfully",
        "data": doc
    }

@router.delete("/{id}")
async def delete_business(id: str, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    result = await db["businesses"].delete_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Business not found")
    return {
        "success": True,
        "message": "Business deleted successfully"
    }
"""

with open("app/core/config.py", "w") as f:
    f.write(config_content)

with open("app/core/security.py", "w") as f:
    f.write(security_update_content)

with open("app/services/auth_service.py", "w") as f:
    f.write(auth_service_content)

with open("app/api/endpoints/auth.py", "w") as f:
    f.write(auth_endpoints_content)

with open("app/api/endpoints/users.py", "w") as f:
    f.write(users_endpoints_content)

with open("app/api/endpoints/businesses.py", "w") as f:
    f.write(businesses_endpoints_content)

api_router_content = """
from fastapi import APIRouter
from app.api.endpoints import auth, users, businesses

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(businesses.router, prefix="/businesses", tags=["Businesses"])
"""

with open("app/api/api_router.py", "w") as f:
    f.write(api_router_content)

env_example_content = """
PORT=8000
MONGODB_URI=mongodb://localhost:27017
JWT_ACCESS_SECRET=your_super_secret_access_key
JWT_REFRESH_SECRET=your_super_secret_refresh_key
TOKEN_ENCRYPTION_KEY=your_token_encryption_key
FRONTEND_URL=http://localhost:3000
NODE_ENV=development
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=user@example.com
SMTP_PASSWORD=secret
"""

with open(".env.example", "w") as f:
    f.write(env_example_content)

# create test file
test_content = """
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_database

@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
async def cleanup_db():
    db = get_database()
    yield
    await db["users"].delete_many({})
    await db["businesses"].delete_many({})
    await db["refresh_sessions"].delete_many({})

@pytest.mark.asyncio
async def test_signup(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    assert res.status_code == 200
    assert res.json()["success"] == True

@pytest.mark.asyncio
async def test_duplicate_signup(async_client):
    req = {
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    }
    await async_client.post("/api/v1/auth/signup", json=req)
    res = await async_client.post("/api/v1/auth/signup", json=req)
    assert res.status_code == 409

@pytest.mark.asyncio
async def test_login(async_client):
    await async_client.post("/api/v1/auth/signup", json={
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    res = await async_client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "Password123"
    })
    assert res.status_code == 200
    assert "accessToken" in res.json()["data"]
    assert "set-cookie" in res.headers
"""

os.makedirs("tests", exist_ok=True)
with open("tests/test_auth.py", "w") as f:
    f.write(test_content)
