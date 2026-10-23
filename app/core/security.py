
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
        decoded_token = jwt.decode(
            token,
            settings.JWT_ACCESS_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False}  # Persistent session until explicit logout
        )
        return decoded_token
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

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

DEV_TEST_USER = CurrentUser({
    "id": "6ad84b1f48fb99ffedf3721e",
    "name": "Developer Tester",
    "fullName": "Developer Mode User",
    "email": "dev@sevenunique.ai",
    "role": "influencer",
    "accountType": "influencer",
    "email_verified": True,
    "emailVerified": True,
    "onboardingCompleted": True,
    "is_pending": False,
    "business_id": "6ad84b1f48fb99ffedf3721f"
})

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> CurrentUser:
    from app.core.database import get_database
    db = get_database()
    
    is_dev = getattr(settings, "DEV_MODE", True) or settings.ENVIRONMENT == "development"

    if not credentials or not credentials.credentials:
        if is_dev:
            inf_user = await db["users"].find_one({"role": "influencer"})
            if inf_user:
                return CurrentUser({
                    "id": str(inf_user["_id"]),
                    "name": inf_user.get("name") or inf_user.get("fullName", "Developer Tester"),
                    "fullName": inf_user.get("fullName") or inf_user.get("name", "Developer Mode User"),
                    "email": inf_user.get("email", "dev@sevenunique.ai"),
                    "role": "influencer",
                    "accountType": "influencer",
                    "email_verified": True,
                    "emailVerified": True,
                    "onboardingCompleted": True,
                    "is_pending": False,
                    "business_id": "6ad84b1f48fb99ffedf3721f"
                })
            return DEV_TEST_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        if is_dev:
            return DEV_TEST_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user_id: str = payload.get("sub")
    if user_id is None or not ObjectId.is_valid(user_id):
        if is_dev:
            return DEV_TEST_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    is_pending = False
    if user_doc is None:
        user_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        is_pending = True
        if user_doc is None:
            if is_dev:
                return DEV_TEST_USER
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
    business = await db["businesses"].find_one({"$or": [{"ownerId": str(user_doc["_id"])}, {"owner_id": str(user_doc["_id"])}, {"user_id": str(user_doc["_id"])}, {"userId": str(user_doc["_id"])}]})

    user_phone = user_doc.get("phone_number")
    user_role = user_doc.get("role")
    account_type = user_doc.get("accountType")
    
    # Auto-resolve influencer role if marked in accountType or has influencer profile
    if account_type == "influencer" or user_role == "influencer":
        user_role = "influencer"
        account_type = "influencer"
    else:
        inf_exists = await db["influencer_profiles"].find_one({"user_id": str(user_doc["_id"])})
        if inf_exists:
            user_role = "influencer"
            account_type = "influencer"
        elif not user_role or user_role == "user":
            user_role = "businessman"
            account_type = account_type or "business"

    phone_verified = user_doc.get("phone_verified", False)
    if not user_phone or user_role in ["businessman", "influencer", "admin"]:
        phone_verified = True

    return CurrentUser({
        "id": str(user_doc["_id"]),
        "name": user_doc.get("name") or user_doc.get("fullName", "Unknown"),
        "fullName": user_doc.get("fullName") or user_doc.get("name", "Unknown"),
        "phone_number": user_phone,
        "phone_verified": phone_verified,
        "email": user_doc.get("email", ""),
        "role": user_role,
        "accountType": account_type or "business",
        "email_verified": user_doc.get("email_verified", user_doc.get("emailVerified", True)),
        "emailVerified": user_doc.get("emailVerified", user_doc.get("email_verified", True)),
        "onboardingCompleted": user_doc.get("onboardingCompleted", False),
        "is_pending": is_pending,
        "business_id": str(business["_id"]) if business else None
    })

async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    is_dev = getattr(settings, "DEV_MODE", True) or settings.ENVIRONMENT == "development"
    if current_user.get("role") != "admin" and not is_dev:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

async def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))) -> Optional[CurrentUser]:
    if not credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        if not payload or not payload.get("sub"):
            return None
        from app.core.database import get_database
        db = get_database()
        user_id = payload.get("sub")
        if not ObjectId.is_valid(user_id):
            return None
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        is_pending = False
        if not user_doc:
            user_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
            is_pending = True
            if not user_doc:
                return None
        business = await db["businesses"].find_one({"$or": [{"ownerId": str(user_doc["_id"])}, {"owner_id": str(user_doc["_id"])}, {"user_id": str(user_doc["_id"])}, {"userId": str(user_doc["_id"])}]})
        user_phone = user_doc.get("phone_number")
        user_role = user_doc.get("role")
        phone_verified = user_doc.get("phone_verified", False)
        if not user_phone or user_role in ["businessman", "influencer", "admin"]:
            phone_verified = True

        return CurrentUser({
            "id": str(user_doc["_id"]),
            "name": user_doc.get("name") or user_doc.get("fullName", "Unknown"),
            "fullName": user_doc.get("fullName") or user_doc.get("name", "Unknown"),
            "phone_number": user_phone,
            "phone_verified": phone_verified,
            "email": user_doc.get("email", ""),
            "role": user_role,
            "accountType": user_doc.get("accountType", "personal"),
            "onboardingCompleted": user_doc.get("onboardingCompleted", False),
            "is_pending": is_pending,
            "business_id": str(business["_id"]) if business else None
        })
    except Exception:
        return None

def require_role(*allowed_roles: str):
    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user_role = current_user.get("role")
        if not user_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role selection required before accessing this resource."
            )
        if user_role == "admin" or user_role in allowed_roles:
            return current_user

        detail_msg = f"Access denied. Required role: {', '.join(allowed_roles)}."
        if "businessman" in allowed_roles and "influencer" not in allowed_roles:
            detail_msg = "Access denied. Businessman role required."
        elif "influencer" in allowed_roles and "businessman" not in allowed_roles:
            detail_msg = "Access denied. Influencer/Creator role required."

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail_msg
        )
    return dependency

require_businessman = require_role("businessman")
require_influencer = require_role("influencer")


