from fastapi import HTTPException, status
from app.core.database import get_database
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin
from app.core.security import get_password_hash, verify_password
from app.services.email_service import EmailService
import random
import string
from datetime import datetime, timedelta, timezone

class EmailNotVerifiedException(Exception):
    pass

class AuthService:
    @staticmethod
    async def get_collection():
        db = get_database()
        return db["users"]

    @staticmethod
    async def get_otp_collection():
        db = get_database()
        # Ensure TTL index
        await db["otps"].create_index("expires_at", expireAfterSeconds=0)
        return db["otps"]

    @staticmethod
    async def get_user_by_email(email: str) -> User | None:
        collection = await AuthService.get_collection()
        doc = await collection.find_one({"email": email.lower().strip()})
        if doc:
            return User(**doc)
        return None

    @staticmethod
    async def resend_otp(email: str):
        collection = await AuthService.get_otp_collection()
        email = email.lower().strip()
        
        now = datetime.now(timezone.utc)
        existing = await collection.find_one({"email": email})
        
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No pending signup found for this email."
            )
            
        if existing.get("last_sent_at"):
            last_sent = existing["last_sent_at"]
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            if (now - last_sent).total_seconds() < 60:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Please wait before requesting another OTP."
                )

        from app.core.config import settings
        if settings.ENVIRONMENT == "development":
            otp = "123456"
        else:
            otp = ''.join(random.choices(string.digits, k=6))
        otp_hash = get_password_hash(otp)
        expires_at = now + timedelta(minutes=10)
        
        # Send email before updating DB to ensure we don't lock out resend if SMTP fails
        await EmailService.send_otp_email(email, otp)
        
        await collection.update_one(
            {"email": email},
            {"$set": {
                "otp_hash": otp_hash,
                "expires_at": expires_at,
                "attempts": 0,
                "last_sent_at": now
            }}
        )

    @staticmethod
    async def verify_otp(email: str, otp: str):
        email = email.lower().strip()
        collection = await AuthService.get_otp_collection()
        doc = await collection.find_one({"email": email})
        
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP expired or invalid."
            )
            
        if doc.get("attempts", 0) >= 5:
            await collection.delete_one({"email": email})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Too many failed attempts. Please request a new OTP."
            )
            
        if not verify_password(otp, doc["otp_hash"]):
            await collection.update_one({"email": email}, {"$inc": {"attempts": 1}})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP."
            )
            
        now = datetime.now(timezone.utc)
        expires_at = doc["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            
        if now > expires_at:
            await collection.delete_one({"email": email})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP expired."
            )
            
        # OTP is valid, perform final duplicate check
        existing_user = await AuthService.get_user_by_email(email)
        if existing_user:
            await collection.delete_one({"email": email})
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists."
            )
            
        users = await AuthService.get_collection()
        
        user = User(
            name=doc.get("name", "User"),
            email=email,
            hashed_password=doc["hashed_password"],
            email_verified=True,
            role=doc.get("role", "business")
        )
        
        user_doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await users.insert_one(user_doc)
        user.id = str(result.inserted_id)
        
        # Provision default Free plan immediately
        from app.services.credit_service import CreditService
        from app.core.database import get_database
        await CreditService.get_or_create_subscription(get_database(), user.id)
        
        # Delete OTP to prevent reuse
        await collection.delete_one({"email": email})
        
        return user

    @staticmethod
    async def handle_signup(user_in: UserCreate) -> User:
        email = user_in.email.lower().strip()
        existing_user = await AuthService.get_user_by_email(email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists."
            )

        hashed_password = get_password_hash(user_in.password)
        
        user_name = user_in.name or getattr(user_in, "fullName", None) or getattr(user_in, "full_name", None) or "User"
        
        users = await AuthService.get_collection()
        user = User(
            name=user_name,
            email=email,
            hashed_password=hashed_password,
            email_verified=True,
            role=user_in.role or "business"
        )
        
        user_doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await users.insert_one(user_doc)
        user.id = str(result.inserted_id)
        
        # Provision default Free plan immediately
        from app.services.credit_service import CreditService
        from app.core.database import get_database
        await CreditService.get_or_create_subscription(get_database(), user.id)
        
        return user

    @staticmethod
    async def authenticate_user(user_login: UserLogin) -> User:
        login_email = (user_login.email or user_login.Email or "").lower().strip()
        login_password = user_login.password or user_login.Password
        
        if not login_email or not login_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email and password are required."
            )
            
        user = await AuthService.get_user_by_email(login_email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password."
            )
        
        if not verify_password(login_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password."
            )
            
        # Check email verification for regular users
        # Default True for existing users who do not have email_verified field
        email_verified = getattr(user, "email_verified", True)
        if user.role != "admin" and not email_verified:
            raise EmailNotVerifiedException("Email verification required")
            
        return user
