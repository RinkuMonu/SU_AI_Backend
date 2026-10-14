
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

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> CurrentUser:
    from app.core.database import get_database
    db = get_database()
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
        
    user_id: str = payload.get("sub")
    if user_id is None or not ObjectId.is_valid(user_id):
        raise credentials_exception
        
    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    is_pending = False
    if user_doc is None:
        user_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        is_pending = True
        if user_doc is None:
            raise credentials_exception
        
    business = await db["businesses"].find_one({"$or": [{"ownerId": str(user_doc["_id"])}, {"owner_id": str(user_doc["_id"])}, {"user_id": str(user_doc["_id"])}, {"userId": str(user_doc["_id"])}]})

    return CurrentUser({
        "id": str(user_doc["_id"]),
        "name": user_doc.get("name") or user_doc.get("fullName", "Unknown"),
        "fullName": user_doc.get("fullName") or user_doc.get("name", "Unknown"),
        "email": user_doc.get("email", ""),
        "role": user_doc.get("role", "user"),
        "accountType": user_doc.get("accountType", "personal"),
        "email_verified": user_doc.get("email_verified", user_doc.get("emailVerified", False)),
        "emailVerified": user_doc.get("emailVerified", user_doc.get("email_verified", False)),
        "onboardingCompleted": user_doc.get("onboardingCompleted", False),
        "is_pending": is_pending,
        "business_id": str(business["_id"]) if business else None
    })

async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.get("role") != "admin":
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
        return CurrentUser({
            "id": str(user_doc["_id"]),
            "name": user_doc.get("name") or user_doc.get("fullName", "Unknown"),
            "fullName": user_doc.get("fullName") or user_doc.get("name", "Unknown"),
            "email": user_doc.get("email", ""),
            "role": user_doc.get("role", "user"),
            "accountType": user_doc.get("accountType", "personal"),
            "onboardingCompleted": user_doc.get("onboardingCompleted", False),
            "is_pending": is_pending,
            "business_id": str(business["_id"]) if business else None
        })
    except Exception:
        return None


