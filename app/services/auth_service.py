import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from app.core.database import get_database
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin
from app.core.security import get_password_hash, verify_password
from app.services.sms_service import SMSService
from app.core.config import settings
from app.utils.phone import normalize_phone_number, mask_phone_number, InvalidPhoneNumberException

logger = logging.getLogger(__name__)

class PhoneNotVerifiedException(Exception):
    """Raised when a phone-identified user has not completed phone OTP verification."""
    pass

def generate_secure_otp(length: int = 6) -> str:
    """Generates a cryptographically secure random numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))

class AuthService:
    @staticmethod
    async def get_collection():
        db = get_database()
        # Sparse unique index on phone_number to prevent collisions while preserving legacy users without phones
        try:
            await db["users"].create_index("phone_number", unique=True, sparse=True)
        except Exception:
            pass
        return db["users"]

    @staticmethod
    async def get_otp_collection():
        db = get_database()
        # Ensure indexes on otps collection
        try:
            await db["otps"].create_index("expires_at", expireAfterSeconds=0)
            await db["otps"].create_index("phone_number", sparse=True)
        except Exception:
            pass
        return db["otps"]

    @staticmethod
    async def get_user_by_email(email: str) -> User | None:
        if not email:
            return None
        collection = await AuthService.get_collection()
        doc = await collection.find_one({"email": email.lower().strip()})
        if doc:
            return User(**doc)
        return None

    @staticmethod
    async def get_user_by_phone(phone_number: str) -> User | None:
        if not phone_number:
            return None
        collection = await AuthService.get_collection()
        doc = await collection.find_one({"phone_number": phone_number})
        if doc:
            return User(**doc)
        return None

    @staticmethod
    async def handle_signup(user_in: UserCreate):
        raw_phone = user_in.phone_number or user_in.phone or user_in.mobile
        raw_email = str(user_in.email).lower().strip() if user_in.email else None

        if not raw_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid mobile phone number is required for registration."
            )

        if not raw_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid email address is required for registration."
            )

        # Normalize phone number
        try:
            phone_number = normalize_phone_number(raw_phone)
        except InvalidPhoneNumberException as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # Duplicate check on existing users
        existing_phone_user = await AuthService.get_user_by_phone(phone_number)
        if existing_phone_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this phone number already exists."
            )

        existing_email_user = await AuthService.get_user_by_email(raw_email)
        if existing_email_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists."
            )

        hashed_password = get_password_hash(user_in.password)
        user_name = user_in.name or user_in.fullName or user_in.full_name or "User"
        now = datetime.now(timezone.utc)

        # Create user directly in database (no email verification, phone verified upon sign-in OTP)
        user = User(
            name=user_name,
            phone_number=phone_number,
            phone_verified=False,
            email=raw_email,
            email_verified=True,
            hashed_password=hashed_password,
            role=None,
            created_at=now,
            updated_at=now
        )

        users_col = await AuthService.get_collection()
        user_doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await users_col.insert_one(user_doc)
        user.id = str(result.inserted_id)

        # Provision default Free subscription immediately
        try:
            from app.services.credit_service import CreditService
            await CreditService.get_or_create_subscription(get_database(), user.id)
        except Exception as e:
            logger.warning(f"Failed to create default subscription for {user.id}: {e}")

        logger.info(f"User created directly on signup: id={user.id}, phone={mask_phone_number(phone_number)}, email={raw_email}")

        return {
            "message": "Account created successfully. Please sign in with your mobile number.",
            "detail": "Account created successfully. Please sign in with your mobile number.",
            "phone_number": mask_phone_number(phone_number),
            "user_id": user.id,
            "code": "SIGNUP_SUCCESS"
        }

    @staticmethod
    async def verify_otp(identifier: str, otp: str):
        cleaned_id = identifier.strip()
        phone_number = None

        try:
            phone_number = normalize_phone_number(cleaned_id)
        except InvalidPhoneNumberException:
            phone_number = None

        collection = await AuthService.get_otp_collection()
        
        # Query OTP by phone number, or by email/id as fallback
        doc = None
        if phone_number:
            doc = await collection.find_one({"phone_number": phone_number})
        if not doc:
            doc = await collection.find_one({"email": cleaned_id.lower()})

        if not doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP expired or invalid."
            )

        if doc.get("attempts", 0) >= 5:
            await collection.delete_one({"_id": doc["_id"]})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Too many failed attempts. Please request a new OTP."
            )

        now = datetime.now(timezone.utc)
        expires_at = doc["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            await collection.delete_one({"_id": doc["_id"]})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OTP expired."
            )

        if not verify_password(otp, doc["otp_hash"]):
            await collection.update_one({"_id": doc["_id"]}, {"$inc": {"attempts": 1}})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP."
            )

        # Single-use: delete OTP record upon successful verification
        await collection.delete_one({"_id": doc["_id"]})

        users = await AuthService.get_collection()
        user_phone = doc.get("phone_number") or phone_number
        user_email = doc.get("email")
        target_user_id = doc.get("user_id")

        # 1. Look up existing registered user
        user_doc = None
        if user_phone:
            user_doc = await users.find_one({"phone_number": user_phone})
        if not user_doc and target_user_id:
            try:
                from bson import ObjectId
                user_doc = await users.find_one({"_id": ObjectId(target_user_id)})
            except Exception:
                pass
        if not user_doc and user_email:
            user_doc = await users.find_one({"email": user_email.lower()})

        if user_doc:
            # Mark user's phone as verified
            await users.update_one(
                {"_id": user_doc["_id"]},
                {"$set": {"phone_verified": True, "updated_at": now}}
            )
            user_doc["phone_verified"] = True
            user = User(**user_doc)
            logger.info(f"User phone verified successfully on login: id={user.id}, phone={mask_phone_number(user.phone_number)}")
            return user

        # 2. Legacy fallback: if user wasn't pre-created in users collection, create now
        user = User(
            name=doc.get("name", "User"),
            phone_number=user_phone,
            phone_verified=True,
            email=user_email,
            email_verified=True,
            hashed_password=doc.get("hashed_password", ""),
            role=None,
            created_at=now,
            updated_at=now
        )
        new_doc = user.model_dump(by_alias=True, exclude={"id"})
        result = await users.insert_one(new_doc)
        user.id = str(result.inserted_id)

        from app.services.credit_service import CreditService
        await CreditService.get_or_create_subscription(get_database(), user.id)

        logger.info(f"Legacy pending user verified & registered: id={user.id}, phone={mask_phone_number(user_phone)}")
        return user

    @staticmethod
    async def resend_otp(identifier: str):
        cleaned_id = identifier.strip()
        phone_number = None

        try:
            phone_number = normalize_phone_number(cleaned_id)
        except InvalidPhoneNumberException:
            phone_number = None

        collection = await AuthService.get_otp_collection()
        now = datetime.now(timezone.utc)

        # Check existing OTP document
        doc = None
        if phone_number:
            doc = await collection.find_one({"phone_number": phone_number})
        if not doc:
            doc = await collection.find_one({"email": cleaned_id.lower()})

        # Also check if user exists in users collection
        user = None
        if phone_number:
            user = await AuthService.get_user_by_phone(phone_number)
        if not user:
            user = await AuthService.get_user_by_email(cleaned_id.lower())

        if not doc and not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No registered user or pending verification found for this phone number."
            )

        # Enforce 60-second cooldown
        if doc and doc.get("last_sent_at"):
            last_sent = doc["last_sent_at"]
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            if (now - last_sent).total_seconds() < 60:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Please wait 60 seconds before requesting another OTP."
                )

        target_phone = phone_number or (user.phone_number if user else None) or (doc.get("phone_number") if doc else None)
        if not target_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid mobile phone number is required to receive OTP."
            )

        otp = generate_secure_otp(6)
        otp_hash = get_password_hash(otp)
        expires_at = now + timedelta(minutes=10)

        # Send via MSG91 SMS gateway
        await SMSService.send_otp(
            phone_number=target_phone,
            otp=otp,
            template_id=settings.MSG91_TEMPLATE_ID_N_REG
        )

        otp_doc = {
            "user_id": str(user.id) if user else (doc.get("user_id") if doc else None),
            "phone_number": target_phone,
            "otp_hash": otp_hash,
            "purpose": "sign_in_verification",
            "expires_at": expires_at,
            "attempts": 0,
            "last_sent_at": now,
            "created_at": now
        }

        await collection.update_one(
            {"phone_number": target_phone},
            {"$set": otp_doc},
            upsert=True
        )

        return {
            "detail": "OTP resent successfully.",
            "phone_number": mask_phone_number(target_phone),
            "code": "OTP_RESENT"
        }

    @staticmethod
    async def authenticate_user(user_login: UserLogin) -> User:
        raw_id = (
            user_login.phone_number
            or user_login.phone
            or user_login.mobile
            or user_login.username
            or user_login.email
            or user_login.Email
            or ""
        ).strip()
        login_password = user_login.password or user_login.Password
        login_otp = user_login.otp

        if not raw_id or not login_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mobile phone number/email and password are required."
            )

        user = None

        # 1. Attempt lookup by normalized phone number
        phone_number = None
        try:
            phone_number = normalize_phone_number(raw_id)
            user = await AuthService.get_user_by_phone(phone_number)
        except InvalidPhoneNumberException:
            user = None

        # 2. Attempt lookup by email (or username)
        if not user:
            user = await AuthService.get_user_by_email(raw_id.lower())

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid mobile phone number/email or password."
            )

        if not verify_password(login_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid mobile phone number/email or password."
            )

        # Administrators log in directly via Admin portal
        if user.role == "admin":
            return user

        # If user supplied OTP directly during login
        if login_otp:
            return await AuthService.verify_otp(
                identifier=user.phone_number or str(user.id),
                otp=login_otp
            )

        # For regular users: Check if phone OTP verification is required
        user_phone = user.phone_number
        if user_phone and not getattr(user, "phone_verified", False):
            # Generate and dispatch OTP to mobile number
            now = datetime.now(timezone.utc)
            otp_collection = await AuthService.get_otp_collection()
            existing_otp = await otp_collection.find_one({"phone_number": user_phone})

            # Check 60s cooldown before sending another SMS
            if existing_otp and existing_otp.get("last_sent_at"):
                last_sent = existing_otp["last_sent_at"]
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                if (now - last_sent).total_seconds() < 60:
                    raise PhoneNotVerifiedException(
                        "Phone OTP verification required. Please enter the OTP sent to your mobile number."
                    )

            otp = generate_secure_otp(6)
            otp_hash = get_password_hash(otp)
            expires_at = now + timedelta(minutes=10)

            await SMSService.send_otp(
                phone_number=user_phone,
                otp=otp,
                template_id=settings.MSG91_TEMPLATE_ID_N_REG
            )

            otp_doc = {
                "user_id": str(user.id),
                "phone_number": user_phone,
                "otp_hash": otp_hash,
                "purpose": "login_verification",
                "expires_at": expires_at,
                "attempts": 0,
                "last_sent_at": now,
                "created_at": now
            }
            await otp_collection.update_one(
                {"phone_number": user_phone},
                {"$set": otp_doc},
                upsert=True
            )

            raise PhoneNotVerifiedException(
                "Phone OTP verification required. An OTP has been sent to your mobile number."
            )

        return user

    @staticmethod
    async def select_role(user_id: str, requested_role: str, client_user_id: str | None = None) -> User:
        """
        Validates, canonicalizes, and persists the selected role for an authenticated user.
        - Enforces one-time onboarding selection (rejects changing to a different role).
        - Handles duplicate identical submissions idempotently.
        - Prevents role escalation to 'admin'.
        - Prevents modifying another user's role.
        """
        from bson import ObjectId

        # 1. Reject attempts to modify other users' roles
        if client_user_id and str(client_user_id).strip() != str(user_id).strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Attempt to change another user's role is forbidden."
            )

        # 2. Validate requested role
        if not requested_role or not isinstance(requested_role, str) or not requested_role.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role. Supported roles are 'businessman' and 'influencer'."
            )

        normalized_input = requested_role.strip().lower()

        # Reject administrative role escalation
        if normalized_input == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized: Cannot assign administrative role."
            )

        # Canonicalize supported roles
        if normalized_input in ["businessman", "business", "merchant"]:
            canonical_role = "businessman"
        elif normalized_input in ["influencer", "creator"]:
            canonical_role = "influencer"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role. Supported roles are 'businessman' and 'influencer'."
            )

        # 3. Fetch user by user_id
        if not ObjectId.is_valid(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid user ID."
            )

        users = await AuthService.get_collection()
        user_doc = await users.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found."
            )

        existing_role = user_doc.get("role")

        # 4. Handle existing role persistence & idempotency
        # If the user already has this exact role selected (duplicate request), succeed safely (idempotent)
        if existing_role == canonical_role:
            logger.info(f"Duplicate role selection '{canonical_role}' received for user {user_id}. Returning existing state.")
            return User(**user_doc)

        # If user already has a DIFFERENT role assigned, reject modifying it (one-time onboarding)
        if existing_role and existing_role not in ["user"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role has already been set and cannot be modified."
            )

        # 5. Persist the selected role
        now = datetime.now(timezone.utc)
        await users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"role": canonical_role, "updated_at": now}}
        )
        user_doc["role"] = canonical_role
        user_doc["updated_at"] = now
        logger.info(f"User {user_id} selected role '{canonical_role}' successfully.")
        return User(**user_doc)

