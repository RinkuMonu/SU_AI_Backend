from fastapi import HTTPException, status, Response
from app.core.database import get_database
from app.models.user import User
from app.models.refresh_session import RefreshSession
from app.schemas.auth import SignupRequest, LoginRequest
from app.core.security import get_password_hash, verify_password, create_access_token
from app.services.email_service import EmailService
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple
from bson import ObjectId
import jwt
import os
import random
import string
import hashlib
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class AuthService:
    @staticmethod
    async def send_otp(email: str, name: Optional[str] = None) -> dict:
        db = get_database()
        clean_email = email.lower().strip()
        
        # Check if already registered
        existing_user = await db["users"].find_one({"email": clean_email})
        if existing_user and existing_user.get("emailVerified"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email is already registered. Please log in."
            )

        now = datetime.now(timezone.utc)
        
        # Cooldown check (45 seconds)
        existing_otp = await db["otps"].find_one({"email": clean_email})
        if existing_otp and existing_otp.get("last_sent_at"):
            last_sent = existing_otp["last_sent_at"]
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            if (now - last_sent).total_seconds() < 45:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Please wait a moment before requesting another OTP."
                )

        otp = f"{random.randint(100000, 999999)}"
        otp_hash = get_password_hash(otp)
        expires_at = now + timedelta(minutes=10)

        await db["otps"].update_one(
            {"email": clean_email},
            {"$set": {
                "email": clean_email,
                "name": name,
                "otp_hash": otp_hash,
                "otp": otp,
                "expires_at": expires_at,
                "attempts": 0,
                "verified": False,
                "last_sent_at": now,
                "updated_at": now
            }},
            upsert=True
        )

        await EmailService.send_otp_email(clean_email, otp)

        return {
            "success": True,
            "message": "Verification OTP sent successfully.",
            "data": {
                "email": clean_email,
                "otp": otp,
                "expiresInMinutes": 10
            }
        }

    @staticmethod
    async def verify_otp(email: str, otp: str) -> dict:
        db = get_database()
        clean_email = email.lower().strip()
        clean_otp = str(otp).strip()

        doc = await db["otps"].find_one({"email": clean_email})
        if not doc:
            # If in dev mode, allow instant verification with 123456
            if clean_otp == "123456" and (settings.ENVIRONMENT == "development" or getattr(settings, "DEV_MODE", False)):
                return {
                    "success": True,
                    "message": "Email verified successfully.",
                    "data": {"email": clean_email}
                }
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No pending verification found or OTP has expired. Please click 'Send OTP' first."
            )

        now = datetime.now(timezone.utc)
        expires_at = doc.get("expires_at")
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now > expires_at:
                await db["otps"].delete_one({"email": clean_email})
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="OTP has expired. Please request a new OTP."
                )

        if doc.get("attempts", 0) >= 5:
            await db["otps"].delete_one({"email": clean_email})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Too many invalid attempts. Please request a new OTP."
            )

        matches = False
        if doc.get("otp") and doc["otp"] == clean_otp:
            matches = True
        elif doc.get("otp_hash") and verify_password(clean_otp, doc["otp_hash"]):
            matches = True
        elif clean_otp == "123456" and (settings.ENVIRONMENT == "development" or getattr(settings, "DEV_MODE", False)):
            matches = True

        if not matches:
            await db["otps"].update_one({"email": clean_email}, {"$inc": {"attempts": 1}})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP. Please check the 6-digit code and try again."
            )

        await db["otps"].update_one(
            {"email": clean_email},
            {"$set": {"verified": True, "verified_at": now}}
        )

        return {
            "success": True,
            "message": "Email OTP verified successfully.",
            "data": {
                "email": clean_email,
                "verified": True
            }
        }

    @staticmethod
    async def signup(req: SignupRequest) -> tuple[User, str, str]:
        db = get_database()
        email = req.email.lower().strip()
        existing = await db["users"].find_one({"email": email})
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        # Email verification is removed / auto-verified
        email_is_verified = True
        
        user = User(
            fullName=req.fullName,
            firstName=req.firstName,
            lastName=req.lastName,
            email=email,
            phone=req.phone or req.contactNumber,
            contactNumber=req.contactNumber or req.phone,
            hashed_password=get_password_hash(req.password),
            accountType="influencer" if (getattr(req, "role", None) == "influencer" or req.accountType == "influencer") else (req.accountType or "business"),
            role="influencer" if (getattr(req, "role", None) == "influencer" or req.accountType == "influencer") else "user",
            termsAcceptedAt=datetime.now(timezone.utc) if req.termsAccepted else None,
            emailVerified=email_is_verified,
            email_verified=email_is_verified,
            emailVerifiedAt=datetime.now(timezone.utc) if email_is_verified else None,
            onboardingCompleted=False,
            onboarding_step=1
        )
        doc = user.model_dump(by_alias=True, exclude={"id"})
        doc["role"] = "influencer" if (getattr(req, "role", None) == "influencer" or req.accountType == "influencer") else "user"
        doc["accountType"] = "influencer" if (getattr(req, "role", None) == "influencer" or req.accountType == "influencer") else (req.accountType or "business")
        doc["onboardingCompleted"] = False
        doc["onboarding_step"] = 1

        # Clear any old abandoned pending registration for this email
        await db["pending_users"].delete_many({"email": email})

        # Save to pending_users ONLY (do NOT save into users collection until onboarding is completed)
        result = await db["pending_users"].insert_one(doc)
        user.id = str(result.inserted_id)

        # Clear OTP records for this email
        await db["otps"].delete_many({"email": email})

        # Generate tokens for onboarding session
        access_token = AuthService.create_token(user.id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
        refresh_token = AuthService.create_token(user.id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))

        return user, access_token, refresh_token

    @classmethod
    async def commit_pending_user(cls, user_id: str, extra_data: dict = None) -> Optional[dict]:
        """
        Moves a pending user from 'pending_users' to 'users' collection once onboarding is completed.
        Also creates initial business record (if business account) and provisions subscription/credits.
        """
        db = get_database()
        if not ObjectId.is_valid(user_id):
            return None

        obj_id = ObjectId(user_id)
        now = datetime.now(timezone.utc)
        pending_doc = await db["pending_users"].find_one({"_id": obj_id})

        if not pending_doc:
            # Check if user already in users collection
            existing_user = await db["users"].find_one({"_id": obj_id})
            if existing_user:
                if extra_data:
                    clean_extra = {k: v for k, v in extra_data.items() if v is not None}
                    clean_extra["onboardingCompleted"] = True
                    clean_extra["updated_at"] = now
                    await db["users"].update_one({"_id": obj_id}, {"$set": clean_extra})
                    existing_user = await db["users"].find_one({"_id": obj_id})
                return existing_user
            return None

        # Build final user document
        final_doc = dict(pending_doc)
        if extra_data:
            for k, v in extra_data.items():
                if v is not None:
                    final_doc[k] = v

        final_doc["onboardingCompleted"] = True
        final_doc["onboarding_completed_at"] = now.isoformat()
        final_doc["updated_at"] = now

        # Save into db["users"] with identical _id
        await db["users"].replace_one({"_id": obj_id}, final_doc, upsert=True)

        # Delete from pending_users
        await db["pending_users"].delete_one({"_id": obj_id})

        # Handle business creation if business persona or business fields provided
        account_type = final_doc.get("accountType", "user")
        biz_name = final_doc.get("business_name")
        if account_type == "business" or biz_name:
            existing_biz = await db["businesses"].find_one({"$or": [{"ownerId": user_id}, {"user_id": user_id}]})
            if not existing_biz:
                company_name = biz_name or f"{final_doc.get('firstName', 'User')}'s Business"
                biz_doc = {
                    "ownerId": user_id,
                    "user_id": user_id,
                    "name": company_name,
                    "category": final_doc.get("business_category") or "General",
                    "location": f"{final_doc.get('city', '')}, {final_doc.get('state', '')}".strip(" ,") or "India",
                    "contact_email": final_doc.get("email"),
                    "contact_phone": final_doc.get("phone") or final_doc.get("contactNumber"),
                    "created_at": now,
                    "updated_at": now
                }
                if final_doc.get("business_type"):
                    biz_doc["type"] = final_doc.get("business_type")
                if final_doc.get("business_description"):
                    biz_doc["description"] = final_doc.get("business_description")
                if final_doc.get("business_logo"):
                    biz_doc["logo"] = final_doc.get("business_logo")
                if final_doc.get("brand_color"):
                    biz_doc["brandColor"] = final_doc.get("brand_color")
                await db["businesses"].insert_one(biz_doc)

        # Handle influencer profile creation if influencer persona
        if account_type == "influencer" or final_doc.get("role") == "influencer":
            existing_inf = await db["influencer_profiles"].find_one({"user_id": str(user_id)})
            if not existing_inf:
                inf_full_name = final_doc.get("fullName") or final_doc.get("name") or "Creator"
                inf_username = final_doc.get("username") or final_doc.get("email", "").split("@")[0] or "creator"
                await db["influencer_profiles"].insert_one({
                    "user_id": str(user_id),
                    "fullName": inf_full_name,
                    "username": inf_username if inf_username.startswith("@") else f"@{inf_username}",
                    "email": final_doc.get("email", ""),
                    "phone": final_doc.get("phone") or final_doc.get("contactNumber") or "",
                    "category": final_doc.get("category") or "Lifestyle & Fashion",
                    "location": f"{final_doc.get('city', '')}, {final_doc.get('state', '')}".strip(" ,") or "India",
                    "follower_count": 0,
                    "engagement_rate": 0.0,
                    "expectedPricePerPost": 5000.0,
                    "created_at": now,
                    "updated_at": now
                })


        # Provision subscription / credits
        try:
            from app.services.credit_service import CreditService
            await CreditService.get_or_create_subscription(db, user_id)
        except Exception as e:
            logger.warning(f"Subscription provisioning error: {e}")

        saved_user = await db["users"].find_one({"_id": obj_id})
        return saved_user

    @staticmethod
    async def register(user_in) -> User:
        db = get_database()
        email = user_in.email.lower().strip()
        existing = await db["users"].find_one({"email": email})
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        hashed_password = get_password_hash(user_in.password)
        user_name = getattr(user_in, "name", None) or getattr(user_in, "fullName", None) or getattr(user_in, "full_name", None) or "User"
        
        user = User(
            fullName=user_name,
            name=user_name,
            email=email,
            hashed_password=hashed_password,
            emailVerified=True,
            email_verified=True,
            role=getattr(user_in, "role", "business") or "business",
            business_logo=getattr(user_in, "business_logo", None),
            brand_color=getattr(user_in, "brand_color", None),
            business_name=getattr(user_in, "business_name", None),
            business_type=getattr(user_in, "business_type", None),
            business_category=getattr(user_in, "business_category", None),
            business_description=getattr(user_in, "business_description", None),
            registration_number=getattr(user_in, "registration_number", None),
            year_established=getattr(user_in, "year_established", None),
            country=getattr(user_in, "country", None),
            state=getattr(user_in, "state", None),
            city=getattr(user_in, "city", None),
            area=getattr(user_in, "area", None),
            pincode=getattr(user_in, "pincode", None),
            full_address=getattr(user_in, "full_address", None),
            google_maps_url=getattr(user_in, "google_maps_url", None),
            business_model=getattr(user_in, "business_model", None),
            selling_model=getattr(user_in, "selling_model", None),
            target_age_group=getattr(user_in, "target_age_group", None),
            target_gender=getattr(user_in, "target_gender", None),
            target_location=getattr(user_in, "target_location", None),
            customer_type=getattr(user_in, "customer_type", None)
        )
        
        user_doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await db["users"].insert_one(user_doc)
        user.id = str(result.inserted_id)
        
        try:
            from app.services.credit_service import CreditService
            await CreditService.get_or_create_subscription(db, user.id)
        except Exception:
            pass
            
        return user

    @staticmethod
    async def login(req: LoginRequest):
        db = get_database()
        email = req.email.lower().strip()
        doc = await db["users"].find_one({"email": email})
        is_pending = False
        if not doc:
            doc = await db["pending_users"].find_one({"email": email})
            is_pending = True

        if not doc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        user = User(**doc)
        if not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if is_pending:
            user.onboardingCompleted = False
            
        access_token = AuthService.create_token(user.id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
        refresh_token = AuthService.create_token(user.id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
        
        # Save refresh session
        rs = RefreshSession(
            userId=str(user.id),
            hashedToken=get_password_hash(hashlib.sha256(refresh_token.encode()).hexdigest()),
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
                if verify_password(hashlib.sha256(refresh_token.encode()).hexdigest(), s["hashedToken"]):
                    valid_session = s
                    break
                    
            if not valid_session:
                raise HTTPException(status_code=401, detail="Session revoked or invalid")
                
            # Rotate refresh token
            await db["refresh_sessions"].update_one({"_id": valid_session["_id"]}, {"$set": {"isRevoked": True}})
            
            access_token = AuthService.create_token(user_id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
            new_refresh_token = AuthService.create_token(user_id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
            
            new_rs = RefreshSession(
                userId=str(user_id),
                hashedToken=get_password_hash(hashlib.sha256(new_refresh_token.encode()).hexdigest()),
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

    @staticmethod
    def create_email_verification_token(user_id: str, email: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=24)
        payload = {
            "sub": str(user_id),
            "email": str(email).lower().strip(),
            "type": "email_verification",
            "exp": expire
        }
        return jwt.encode(payload, settings.JWT_ACCESS_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def extract_token(token_or_link: str) -> str:
        """Extract pure token string whether user passed raw token, Bearer token, or full URL link."""
        if not token_or_link:
            return ""
        val = str(token_or_link).strip()
        if val.startswith("Bearer "):
            val = val[7:].strip()
        if "token=" in val:
            import urllib.parse
            parsed = urllib.parse.urlparse(val)
            query_params = urllib.parse.parse_qs(parsed.query)
            if "token" in query_params and query_params["token"]:
                return query_params["token"][0].strip()
        return val

    @staticmethod
    async def verify_email(token_or_link: str) -> dict:
        db = get_database()
        clean_token = AuthService.extract_token(token_or_link)
        if not clean_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please provide a valid verification link or token."
            )

        payload = None
        try:
            payload = jwt.decode(clean_token, settings.JWT_ACCESS_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification link or token has expired. Please request a new one."
            )
        except jwt.InvalidTokenError:
            # Fallback to REFRESH_SECRET in case a refresh token was supplied
            try:
                payload = jwt.decode(clean_token, settings.JWT_REFRESH_SECRET, algorithms=[settings.JWT_ALGORITHM])
            except Exception:
                pass

        user = None
        if payload:
            user_id = payload.get("sub")
            email = payload.get("email")

            if user_id:
                try:
                    user = await db["users"].find_one({"_id": ObjectId(user_id)})
                except Exception:
                    pass
            if not user and email:
                user = await db["users"].find_one({"email": email.lower().strip()})

        # Check if clean_token matches stored verificationToken directly in database
        if not user:
            user = await db["users"].find_one({"verificationToken": clean_token})

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification link or token."
            )

        if user.get("emailVerified"):
            return {
                "email": user["email"],
                "fullName": user.get("fullName", ""),
                "alreadyVerified": True
            }

        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": {
                "emailVerified": True,
                "emailVerifiedAt": datetime.now(timezone.utc),
                "verificationToken": None
            }}
        )

        return {
            "email": user["email"],
            "fullName": user.get("fullName", ""),
            "alreadyVerified": False
        }

    @staticmethod
    async def resend_verification(email: str, force: bool = False) -> dict:
        db = get_database()
        clean_email = email.lower().strip()
        user = await db["users"].find_one({"email": clean_email})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account registered with this email address."
            )

        if user.get("emailVerified") and not force:
            return {
                "alreadyVerified": True,
                "message": "Email is already verified."
            }

        if force and user.get("emailVerified"):
            await db["users"].update_one(
                {"_id": user["_id"]},
                {"$set": {"emailVerified": False, "emailVerifiedAt": None}}
            )

        user_id = str(user["_id"])
        verification_token = AuthService.create_email_verification_token(user_id, clean_email)

        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": {"verificationToken": verification_token}}
        )

        verification_link = f"{settings.BACKEND_URL}/api/v1/auth/verify-email?token={verification_token}"
        await EmailService.send_verification_email(
            to_email=clean_email,
            verification_link=verification_link,
            full_name=user.get("fullName")
        )

        return {
            "alreadyVerified": False,
            "message": "Verification email sent successfully.",
            "data": {
                "email": clean_email,
                "verificationLink": verification_link,
                "token": verification_token
            }
        }


    @staticmethod
    def create_password_reset_token(user_id: str, email: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
        payload = {
            "sub": str(user_id),
            "email": str(email).lower().strip(),
            "type": "password_reset",
            "exp": expire
        }
        return jwt.encode(payload, settings.JWT_ACCESS_SECRET, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    async def forgot_password(email: str) -> dict:
        db = get_database()
        clean_email = email.lower().strip()
        user = await db["users"].find_one({"email": clean_email})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account registered with this email address."
            )

        user_id = str(user["_id"])
        reset_token = AuthService.create_password_reset_token(user_id, clean_email)
        expire_time = datetime.now(timezone.utc) + timedelta(hours=1)

        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": {
                "resetPasswordToken": reset_token,
                "resetPasswordExpiresAt": expire_time
            }}
        )

        reset_link = f"{settings.BACKEND_URL}/api/v1/auth/reset-password?token={reset_token}"
        await EmailService.send_password_reset_email(
            to_email=clean_email,
            reset_link=reset_link,
            full_name=user.get("fullName")
        )

        return {
            "success": True,
            "message": "Password reset link sent to your email successfully.",
            "data": {
                "email": clean_email,
                "resetLink": reset_link,
                "token": reset_token
            }
        }

    @staticmethod
    async def reset_password(token_or_link: str, new_password: str, confirm_password: Optional[str] = None) -> dict:
        db = get_database()

        if confirm_password is not None and new_password != confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Passwords do not match."
            )

        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long."
            )

        clean_token = AuthService.extract_token(token_or_link)
        if not clean_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please provide a valid password reset link or token."
            )

        payload = None
        try:
            payload = jwt.decode(clean_token, settings.JWT_ACCESS_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset link has expired. Please request a new one."
            )
        except jwt.InvalidTokenError:
            pass

        user = None
        if payload:
            user_id = payload.get("sub")
            email = payload.get("email")
            if user_id:
                try:
                    user = await db["users"].find_one({"_id": ObjectId(user_id)})
                except Exception:
                    pass
            if not user and email:
                user = await db["users"].find_one({"email": email.lower().strip()})

        # Also check stored resetPasswordToken if not found
        if not user:
            user = await db["users"].find_one({"resetPasswordToken": clean_token})

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset link."
            )

        # Check expiration in DB if stored
        if user.get("resetPasswordExpiresAt"):
            expires_at = user["resetPasswordExpiresAt"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password reset link has expired. Please request a new one."
                )

        # Hash new password
        hashed = get_password_hash(new_password)

        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": {
                "hashed_password": hashed,
                "resetPasswordToken": None,
                "resetPasswordExpiresAt": None,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        # Invalidate existing refresh sessions
        await db["refresh_sessions"].update_many(
            {"userId": str(user["_id"])},
            {"$set": {"isRevoked": True}}
        )

        return {
            "success": True,
            "message": "Password reset successfully. You can now log in with your new password.",
            "data": {
                "email": user["email"]
            }
        }

