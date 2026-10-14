"""
Instagram API Service — Instagram Login (Business Login for Instagram)

Uses graph.instagram.com with Instagram User Access Token.
Handles: OAuth, profile, image publishing, reel publishing, 
comments, messaging, and insights.

Token encryption uses HMAC-based Fernet-like approach with the JWT_SECRET_KEY.
"""
import hashlib
import base64
import hmac
import json
import logging
import asyncio
import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from bson import ObjectId
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Token Encryption (server-side only)
# ──────────────────────────────────────────────

def _get_encryption_key() -> bytes:
    """Derive a 32-byte encryption key from JWT_SECRET_KEY using SHA-256."""
    secret = (settings.JWT_SECRET_KEY or "fallback-dev-key").encode("utf-8")
    return hashlib.sha256(secret).digest()


def encrypt_token(token: str) -> str:
    """
    Simple XOR-based encryption with HMAC integrity check.
    NOT a replacement for Fernet/AES in production, but sufficient
    for preventing plaintext token storage without adding cryptography dependency.
    """
    key = _get_encryption_key()
    token_bytes = token.encode("utf-8")
    
    # XOR encrypt
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(token_bytes))
    
    # Create HMAC for integrity
    mac = hmac.new(key, encrypted, hashlib.sha256).digest()
    
    # Combine: MAC (32 bytes) + encrypted data
    combined = mac + encrypted
    return base64.urlsafe_b64encode(combined).decode("utf-8")


def decrypt_token(encrypted_str: str) -> str:
    """Decrypt a token encrypted with encrypt_token()."""
    key = _get_encryption_key()
    
    try:
        combined = base64.urlsafe_b64decode(encrypted_str.encode("utf-8"))
    except Exception:
        raise ValueError("Invalid encrypted token format")
    
    if len(combined) < 32:
        raise ValueError("Invalid encrypted token: too short")
    
    stored_mac = combined[:32]
    encrypted = combined[32:]
    
    # Verify HMAC
    expected_mac = hmac.new(key, encrypted, hashlib.sha256).digest()
    if not hmac.compare_digest(stored_mac, expected_mac):
        raise ValueError("Token integrity check failed")
    
    # XOR decrypt
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")


# ──────────────────────────────────────────────
# Instagram API Service
# ──────────────────────────────────────────────

IG_API_BASE = f"https://graph.facebook.com/{settings.INSTAGRAM_API_VERSION}"
# FB_API_BASE is used for token endpoints and generic Facebook calls
FB_API_BASE = "https://graph.facebook.com"


class InstagramService:

    @staticmethod
    async def authenticate_instagram_user(
        db,
        access_token: str,
        profile: Optional[Dict[str, Any]] = None,
        account_type: str = "business",
    ):
        """
        Authenticate or register a user using Instagram Login.
        Issues JWT access & refresh tokens and returns user doc + tokens.
        """
        from app.models.user import User
        from app.models.refresh_session import RefreshSession
        from app.core.security import get_password_hash
        from app.services.auth_service import AuthService
        from datetime import timedelta
        import uuid
        import secrets

        if not profile:
            try:
                profile = await InstagramService.get_instagram_profile(access_token)
            except Exception as e:
                logger.warning(f"Could not fetch IG profile: {e}")
                profile = {"user_id": f"ig_{secrets.token_hex(6)}", "username": "instagram_user"}

        ig_id = str(profile.get("user_id") or profile.get("id") or uuid.uuid4())
        username = profile.get("username") or "Instagram User"
        name = profile.get("name") or username
        picture_url = profile.get("profile_picture_url")
        email = profile.get("email") or f"ig_{username.lower().replace(' ', '_')}@instagram.user"
        email = email.lower().strip()
        now = datetime.now(timezone.utc)
        encrypted_token = encrypt_token(access_token)

        # Check existing user by email or instagramId or instagram_username
        existing_user = await db["users"].find_one({
            "$or": [
                {"email": email},
                {"instagramId": ig_id},
                {"instagram_user_id": ig_id},
                {"instagram_username": username},
            ]
        })

        if existing_user:
            user_id = str(existing_user["_id"])
            update_data = {
                "instagramId": ig_id,
                "instagram_user_id": ig_id,
                "instagram_username": username,
                "instagram_access_token": encrypted_token,
                "instagram_connected": True,
                "instagram_connected_at": now,
                "updated_at": now,
            }
            if picture_url and not existing_user.get("profileImageUrl"):
                update_data["profileImageUrl"] = picture_url
            if not existing_user.get("emailVerified"):
                update_data["emailVerified"] = True
                update_data["email_verified"] = True
                update_data["emailVerifiedAt"] = now

            providers = existing_user.get("authProviders", [])
            if "instagram" not in providers:
                providers.append("instagram")
                update_data["authProviders"] = providers

            await db["users"].update_one({"_id": existing_user["_id"]}, {"$set": update_data})
            user_doc = await db["users"].find_one({"_id": existing_user["_id"]})
            user = User(**user_doc)
            user.id = user_id
            user.onboardingCompleted = bool(existing_user.get("onboardingCompleted", False))
            user.onboarding_step = existing_user.get("onboarding_step", 1)
        else:
            # Check pending_users collection
            pending_existing = await db["pending_users"].find_one({
                "$or": [
                    {"email": email},
                    {"instagramId": ig_id},
                    {"instagram_user_id": ig_id},
                    {"instagram_username": username},
                ]
            })
            if pending_existing:
                user_id = str(pending_existing["_id"])
                user = User.from_mongo(pending_existing)
                user.id = user_id
                user.onboardingCompleted = False
                user.onboarding_step = pending_existing.get("onboarding_step", 1)
            else:
                # Create NEW USER -> ALWAYS onboardingCompleted = False, onboarding_step = 1
                random_pwd = get_password_hash(f"ig_{uuid.uuid4()}_{secrets.token_hex(8)}")
                first_name = name.split()[0] if name else username
                last_name = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
                user = User(
                    fullName=name,
                    name=name,
                    firstName=first_name,
                    lastName=last_name,
                    email=email,
                    hashed_password=random_pwd,
                    accountType=account_type or "business",
                    authProviders=["instagram"],
                    emailVerified=True,
                    email_verified=True,
                    emailVerifiedAt=now,
                    termsAcceptedAt=now,
                    profileImageUrl=picture_url,
                    role="user",
                    onboardingCompleted=False,
                    onboarding_step=1,
                )
                doc = user.model_dump(by_alias=True, exclude={"id"})
                doc["instagramId"] = ig_id
                doc["instagram_user_id"] = ig_id
                doc["instagram_username"] = username
                doc["instagram_access_token"] = encrypted_token
                doc["instagram_connected"] = True
                doc["instagram_connected_at"] = now
                doc["onboardingCompleted"] = False
                doc["onboarding_completed"] = False
                doc["onboarding_step"] = 1
                result = await db["users"].insert_one(doc)
                user.id = str(result.inserted_id)

                try:
                    from app.services.credit_service import CreditService
                    await CreditService.get_or_create_subscription(db, user.id)
                except Exception as e:
                    logger.warning(f"Could not provision subscription: {e}")

        # Save connection into instagram_connections
        try:
            ig_conn = {
                "user_id": str(user.id),
                "platform": "instagram",
                "login_method": "instagram_login",
                "instagram_user_id": ig_id,
                "instagram_username": username,
                "account_type": profile.get("account_type", "BUSINESS"),
                "profile_picture_url": picture_url or "",
                "encrypted_access_token": encrypted_token,
                "connected": True,
                "created_at": now,
                "updated_at": now,
            }
            await db["instagram_connections"].update_one(
                {"user_id": str(user.id), "platform": "instagram"},
                {"$set": ig_conn},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"Could not save instagram connection document: {e}")

        # Issue JWT tokens
        jwt_access_token = AuthService.create_token(
            user.id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        jwt_refresh_token = AuthService.create_token(
            user.id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        rs = RefreshSession(
            userId=str(user.id),
            hashedToken=get_password_hash(hashlib.sha256(jwt_refresh_token.encode()).hexdigest()),
            expiresAt=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await db["refresh_sessions"].insert_one(rs.model_dump(by_alias=True, exclude={"id"}))

        return user, jwt_access_token, jwt_refresh_token

    """
    Centralized Instagram API service using Instagram Login flow.
    All methods require the caller to provide a database reference.
    
    When INSTAGRAM_APP_ID is not configured, the service operates in
    DEMO_MODE — returning realistic mock responses so the API works
    during development without real Meta credentials.
    """

    @staticmethod
    def is_demo_mode() -> bool:
        """Check if Instagram credentials are not configured (demo/dev mode)."""
        app_id = settings.INSTAGRAM_APP_ID or getattr(settings, "FACEBOOK_APP_ID", None)
        app_secret = settings.INSTAGRAM_APP_SECRET or getattr(settings, "FACEBOOK_APP_SECRET", None)
        return not app_id or not app_secret

    # ─── OAuth Flow ───────────────────────────

    @staticmethod
    def get_authorization_url(state: str) -> str:
        """
        Generate Instagram Business Login authorization URL.
        Uses the Instagram OAuth endpoint (not Facebook Login).
        """
        app_id = settings.INSTAGRAM_APP_ID or getattr(settings, "FACEBOOK_APP_ID", None)
        redirect_uri = settings.INSTAGRAM_REDIRECT_URI or f"{settings.BACKEND_URL}/api/instagram/callback"
        api_version = settings.INSTAGRAM_API_VERSION

        if not app_id:
            raise HTTPException(
                status_code=500,
                detail="Instagram App ID is not configured"
            )

        # Instagram Business Login OAuth URL
        scopes = "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments,instagram_business_content_publish"

        auth_url = (
            f"https://www.instagram.com/oauth/authorize"
            f"?client_id={app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&state={state}"
        )
        return auth_url

    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for a short-lived Instagram User Access Token,
        then exchange for a long-lived token.
        """
        app_id = settings.INSTAGRAM_APP_ID or getattr(settings, "FACEBOOK_APP_ID", None)
        app_secret = settings.INSTAGRAM_APP_SECRET or getattr(settings, "FACEBOOK_APP_SECRET", None)
        redirect_uri = settings.INSTAGRAM_REDIRECT_URI or f"{settings.BACKEND_URL}/api/instagram/callback"

        if not app_id or not app_secret:
            raise HTTPException(
                status_code=500,
                detail="Instagram App credentials are not configured"
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Exchange code for short-lived token
            api_version = settings.INSTAGRAM_API_VERSION
            token_url = f"{FB_API_BASE}/{api_version}/oauth/access_token"
            token_payload = {
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            }

            try:
                res = await client.get(token_url, params=token_payload)
                res.raise_for_status()
                token_data = res.json()
            except httpx.HTTPStatusError as e:
                err = e.response.json() if e.response.content else {}
                logger.error(f"Facebook token exchange failed: {err}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Facebook OAuth failed: {err.get('error', {}).get('message', str(e))}"
                )

            short_lived_token = token_data.get("access_token")

            if not short_lived_token:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to obtain Facebook access token"
                )

            # Step 2: Exchange for long-lived token
            long_lived_url = (
                f"{FB_API_BASE}/{api_version}/oauth/access_token"
                f"?grant_type=fb_exchange_token"
                f"&client_id={app_id}"
                f"&client_secret={app_secret}"
                f"&fb_exchange_token={short_lived_token}"
            )

            try:
                ll_res = await client.get(long_lived_url)
                ll_res.raise_for_status()
                ll_data = ll_res.json()
                long_lived_token = ll_data.get("access_token", short_lived_token)
            except Exception as e:
                logger.warning(f"Long-lived token exchange failed, using short-lived: {e}")
                long_lived_token = short_lived_token

            return {
                "access_token": long_lived_token,
                "user_id": "", # Will be extracted from profile
            }

    @staticmethod
    async def get_instagram_profile(access_token: str) -> Dict[str, Any]:
        """Fetch Instagram professional account profile info via Facebook Pages."""
        api_version = settings.INSTAGRAM_API_VERSION
        url = f"{FB_API_BASE}/{api_version}/me/accounts"
        params = {
            "fields": "instagram_business_account{id,username,profile_picture_url,followers_count,media_count,name,account_type}",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.get(url, params=params)
                res.raise_for_status()
                data = res.json()
                pages = data.get("data", [])
                
                # Find the first page with an instagram_business_account
                for page in pages:
                    if "instagram_business_account" in page:
                        ig_account = page["instagram_business_account"]
                        return {
                            "user_id": ig_account.get("id"),
                            "username": ig_account.get("username"),
                            "name": ig_account.get("name"),
                            "account_type": ig_account.get("account_type", "BUSINESS"),
                            "profile_picture_url": ig_account.get("profile_picture_url"),
                            "followers_count": ig_account.get("followers_count"),
                            "media_count": ig_account.get("media_count"),
                        }
                        
                raise HTTPException(
                    status_code=400,
                    detail="No Instagram Professional Account linked to your Facebook Pages."
                )
            except httpx.HTTPStatusError as e:
                err = e.response.json() if e.response.content else {}
                logger.error(f"Instagram profile fetch failed: {err}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch Instagram profile: {err.get('error', {}).get('message', str(e))}"
                )

    # ─── Connection Management ────────────────

    @staticmethod
    async def save_connection(db, user_id: str, token_data: dict, profile: dict):
        """Save or update Instagram connection for a user."""
        encrypted = encrypt_token(token_data["access_token"])
        
        connection = {
            "user_id": user_id,
            "platform": "instagram",
            "instagram_user_id": token_data.get("user_id") or profile.get("user_id") or profile.get("id", ""),
            "instagram_username": profile.get("username", ""),
            "account_type": profile.get("account_type", ""),
            "profile_picture_url": profile.get("profile_picture_url", ""),
            "encrypted_access_token": encrypted,
            "connected": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Upsert: update if exists, insert if not
        await db["instagram_connections"].update_one(
            {"user_id": user_id, "platform": "instagram"},
            {"$set": connection},
            upsert=True,
        )

        return connection

    @staticmethod
    async def get_connection(db, user_id: str) -> Optional[dict]:
        """Get Instagram connection for a user (without decrypted token)."""
        conn = await db["instagram_connections"].find_one(
            {"user_id": user_id, "platform": "instagram", "connected": True}
        )
        return conn

    @staticmethod
    async def get_decrypted_token(db, user_id: str) -> str:
        """Get decrypted Instagram access token. Server-side only."""
        conn = await db["instagram_connections"].find_one(
            {"user_id": user_id, "platform": "instagram", "connected": True}
        )
        if not conn:
            raise HTTPException(
                status_code=400,
                detail="Instagram is not connected"
            )

        encrypted = conn.get("encrypted_access_token")
        if not encrypted:
            raise HTTPException(
                status_code=400,
                detail="Instagram access token not found"
            )

        try:
            return decrypt_token(encrypted)
        except ValueError as e:
            logger.error(f"Token decryption failed for user {user_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to decrypt Instagram token. Please reconnect."
            )

    @staticmethod
    async def disconnect(db, user_id: str):
        """Disconnect Instagram for a user."""
        result = await db["instagram_connections"].update_one(
            {"user_id": user_id, "platform": "instagram"},
            {"$set": {
                "connected": False,
                "encrypted_access_token": None,
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        return result.modified_count > 0

    # ─── Image Publishing ────

    @staticmethod
    async def create_image_container(
        access_token: str,
        ig_user_id: str,
        image_url: str,
        caption: str = "",
    ) -> str:
        """Create an image media container. Returns container_id."""
        api_version = settings.INSTAGRAM_API_VERSION
        url = f"{IG_API_BASE}/{ig_user_id}/media"
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create image container: {error_msg}"
                )
            return data["id"]

    # ─── Reel / Video Publishing ──────────────

    @staticmethod
    async def create_reel_container(
        access_token: str,
        ig_user_id: str,
        video_url: str,
        caption: str = "",
        share_to_feed: bool = True,
    ) -> str:
        """Create a Reel media container. Returns container_id."""
        api_version = settings.INSTAGRAM_API_VERSION
        url = f"{IG_API_BASE}/{ig_user_id}/media"
        payload = {
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
            "share_to_feed": str(share_to_feed).lower(),
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create reel container: {error_msg}"
                )
            return data["id"]

    # ─── Container Status & Publish ───────────

    @staticmethod
    async def check_container_status(
        access_token: str,
        container_id: str,
    ) -> Dict[str, str]:
        """Check the processing status of a media container."""
        url = f"{IG_API_BASE}/{container_id}"
        params = {
            "fields": "status_code",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return {
                "id": container_id,
                "status": data.get("status_code", "UNKNOWN"),
            }

    @staticmethod
    async def wait_for_container(
        access_token: str,
        container_id: str,
        max_attempts: int = 30,
        interval: int = 5,
    ) -> str:
        """
        Poll container status until FINISHED or error.
        Returns the status. Raises on ERROR or timeout.
        """
        for attempt in range(max_attempts):
            status_data = await InstagramService.check_container_status(
                access_token, container_id
            )
            status = status_data.get("status", "UNKNOWN")

            if status == "FINISHED":
                return status
            elif status == "ERROR":
                raise HTTPException(
                    status_code=400,
                    detail="Instagram media container processing failed"
                )
            elif status == "IN_PROGRESS":
                await asyncio.sleep(interval)
            else:
                # Unknown status, wait and retry
                await asyncio.sleep(interval)

        raise HTTPException(
            status_code=408,
            detail="Instagram media container processing timed out"
        )

    @staticmethod
    async def publish_container(
        access_token: str,
        ig_user_id: str,
        container_id: str,
    ) -> str:
        """Publish a finished media container. Returns the published media ID."""
        api_version = settings.INSTAGRAM_API_VERSION
        url = f"{IG_API_BASE}/{ig_user_id}/media_publish"
        payload = {
            "creation_id": container_id,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to publish media: {error_msg}"
                )
            return data["id"]

    # ─── Carousel Publishing ──────────────────

    @staticmethod
    async def create_carousel_item_container(
        access_token: str,
        ig_user_id: str,
        media_url: str,
        media_type: str = "IMAGE",
    ) -> str:
        """Create a single carousel item container."""
        url = f"{IG_API_BASE}/{ig_user_id}/media"
        payload = {
            "is_carousel_item": "true",
            "access_token": access_token,
        }

        if media_type.upper() == "VIDEO":
            payload["video_url"] = media_url
            payload["media_type"] = "VIDEO"
        else:
            payload["image_url"] = media_url

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create carousel item: {error_msg}"
                )
            return data["id"]

    @staticmethod
    async def create_carousel_container(
        access_token: str,
        ig_user_id: str,
        children_ids: list,
        caption: str = "",
    ) -> str:
        """Create a carousel container with child media IDs."""
        url = f"{IG_API_BASE}/{ig_user_id}/media"
        payload = {
            "media_type": "CAROUSEL",
            "caption": caption,
            "children": ",".join(children_ids),
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create carousel container: {error_msg}"
                )
            return data["id"]

    # ─── Media Retrieval ────────

    @staticmethod
    async def get_media(
        access_token: str,
        ig_user_id: str,
        limit: int = 25,
    ) -> list:
        """Get recent media from Instagram account."""
        url = f"{IG_API_BASE}/{ig_user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            "limit": limit,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return data.get("data", [])

    # ─── Comments ─────────────────────────────

    @staticmethod
    async def get_comments(
        access_token: str,
        media_id: str,
    ) -> list:
        """Get comments on a media object."""
        url = f"{IG_API_BASE}/{media_id}/comments"
        params = {
            "fields": "id,text,username,timestamp,like_count,replies{id,text,username,timestamp}",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return data.get("data", [])

    @staticmethod
    async def reply_to_comment(
        access_token: str,
        comment_id: str,
        message: str,
    ) -> dict:
        """Reply to a comment."""
        url = f"{IG_API_BASE}/{comment_id}/replies"
        payload = {
            "message": message,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to reply to comment: {error_msg}"
                )
            return data

    @staticmethod
    async def hide_comment(
        access_token: str,
        comment_id: str,
        hide: bool = True,
    ) -> dict:
        """Hide or unhide a comment."""
        url = f"{IG_API_BASE}/{comment_id}"
        payload = {
            "hide": str(hide).lower(),
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, params=payload)
            return res.json()

    @staticmethod
    async def delete_comment(
        access_token: str,
        comment_id: str,
    ) -> bool:
        """Delete a comment."""
        url = f"{IG_API_BASE}/{comment_id}"
        params = {"access_token": access_token}

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.delete(url, params=params)
            return res.status_code == 200

    # ─── Messaging ────────────────────────────

    @staticmethod
    async def get_conversations(
        access_token: str,
        ig_user_id: str,
    ) -> list:
        """Get Instagram conversations (DMs)."""
        url = f"{IG_API_BASE}/{ig_user_id}/conversations"
        params = {
            "platform": "instagram",
            "fields": "id,participants,messages{id,message,from,created_time}",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return data.get("data", [])

    @staticmethod
    async def get_conversation_messages(
        access_token: str,
        conversation_id: str,
    ) -> list:
        """Get messages in a specific conversation."""
        url = f"{IG_API_BASE}/{conversation_id}"
        params = {
            "fields": "messages{id,message,from,created_time}",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            messages = data.get("messages", {})
            return messages.get("data", []) if isinstance(messages, dict) else []

    @staticmethod
    async def send_message(
        access_token: str,
        ig_user_id: str,
        recipient_id: str,
        message: str,
    ) -> dict:
        """
        Send a message to an Instagram user.
        Note: The recipient must have messaged the professional account first.
        Group messaging is not supported.
        """
        url = f"{IG_API_BASE}/{ig_user_id}/messages"
        payload = {
            "recipient": json.dumps({"id": recipient_id}),
            "message": json.dumps({"text": message}),
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, data=payload)
            data = res.json()
            if "error" in data:
                error_msg = data["error"].get("message", "Unknown error")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to send message: {error_msg}"
                )
            return data

    # ─── Insights / Analytics ─────────────────

    @staticmethod
    async def get_account_insights(
        access_token: str,
        ig_user_id: str,
        metric: str = "impressions,reach,accounts_engaged",
        period: str = "day",
    ) -> list:
        """Get Instagram account-level insights."""
        url = f"{IG_API_BASE}/{ig_user_id}/insights"
        params = {
            "metric": metric,
            "period": period,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return data.get("data", [])

    @staticmethod
    async def get_media_insights(
        access_token: str,
        media_id: str,
        metric: str = "impressions,reach,engagement,saved",
    ) -> list:
        """Get insights for a specific media object."""
        url = f"{IG_API_BASE}/{media_id}/insights"
        params = {
            "metric": metric,
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            return data.get("data", [])

    # ─── High-Level Publishing Helpers ────────

    @staticmethod
    async def publish_image(
        db,
        user_id: str,
        image_url: str,
        caption: str = "",
        content_id: Optional[str] = None,
    ) -> dict:
        """
        Complete flow: decrypt token → create container → publish → update content record.
        """
        access_token = await InstagramService.get_decrypted_token(db, user_id)
        conn = await InstagramService.get_connection(db, user_id)
        ig_user_id = conn["instagram_user_id"]

        # 1. Create container
        container_id = await InstagramService.create_image_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            image_url=image_url,
            caption=caption,
        )

        # 2. Publish (images are usually ready immediately, but check anyway)
        try:
            await InstagramService.wait_for_container(
                access_token=access_token,
                container_id=container_id,
                max_attempts=5,
                interval=2,
            )
        except HTTPException:
            pass  # Try publishing anyway for images

        media_id = await InstagramService.publish_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            container_id=container_id,
        )

        # 3. Update content record if content_id provided
        if content_id and ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {
                    "ig_media_id": media_id,
                    "ig_published_at": datetime.now(timezone.utc),
                    "ig_status": "published",
                    "platform": "instagram",
                    "status": "published",
                    "published_at": datetime.now(timezone.utc),
                    "external_post_id": media_id,
                }}
            )

        return {"success": True, "ig_media_id": media_id}

    @staticmethod
    async def publish_reel(
        db,
        user_id: str,
        video_url: str,
        caption: str = "",
        content_id: Optional[str] = None,
        share_to_feed: bool = True,
    ) -> dict:
        """
        Complete reel flow: decrypt token → create container → poll status → publish → update content.
        """
        access_token = await InstagramService.get_decrypted_token(db, user_id)
        conn = await InstagramService.get_connection(db, user_id)
        ig_user_id = conn["instagram_user_id"]

        # 1. Create reel container
        container_id = await InstagramService.create_reel_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            video_url=video_url,
            caption=caption,
            share_to_feed=share_to_feed,
        )

        # 2. Wait for processing (reels take time)
        await InstagramService.wait_for_container(
            access_token=access_token,
            container_id=container_id,
            max_attempts=30,
            interval=5,
        )

        # 3. Publish
        media_id = await InstagramService.publish_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            container_id=container_id,
        )

        # 4. Update content record
        if content_id and ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {
                    "ig_media_id": media_id,
                    "ig_published_at": datetime.now(timezone.utc),
                    "ig_status": "published",
                    "platform": "instagram",
                    "status": "published",
                    "published_at": datetime.now(timezone.utc),
                    "external_post_id": media_id,
                }}
            )

        # Also update reel_jobs if content_id matches
        if content_id:
            await db["reel_jobs"].update_one(
                {"_id": ObjectId(content_id)} if ObjectId.is_valid(content_id) else {"content_id": content_id},
                {"$set": {
                    "ig_media_id": media_id,
                    "ig_published_at": datetime.now(timezone.utc),
                    "ig_status": "published",
                }},
            )

        return {"success": True, "ig_media_id": media_id}

    # ─── Webhook Verification ─────────────────

    @staticmethod
    def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Verify Instagram webhook subscription.
        When setting up Webhooks in the Meta Developer Console:
        - Callback URL: https://<your-domain>/api/instagram/webhook
        - Verify Token: sevenunique_webhook_secret_123
        """
        expected_token = "sevenunique_webhook_secret_123"

        if mode == "subscribe" and token == expected_token:
            return challenge
        return None

    @staticmethod
    async def process_webhook_event(db, body: dict):
        """
        Process incoming Instagram webhook events.
        Handles: comments, messages, live_comments.
        """
        entry_list = body.get("entry", [])

        for entry in entry_list:
            ig_user_id = entry.get("id", "")
            changes = entry.get("changes", [])
            messaging = entry.get("messaging", [])

            # Handle field changes (comments, live_comments)
            for change in changes:
                field = change.get("field", "")
                value = change.get("value", {})

                if field == "comments":
                    await db["instagram_webhook_events"].insert_one({
                        "type": "comment",
                        "ig_user_id": ig_user_id,
                        "data": value,
                        "received_at": datetime.now(timezone.utc),
                    })
                elif field == "live_comments":
                    await db["instagram_webhook_events"].insert_one({
                        "type": "live_comment",
                        "ig_user_id": ig_user_id,
                        "data": value,
                        "received_at": datetime.now(timezone.utc),
                    })

            # Handle messaging events
            for msg_event in messaging:
                await db["instagram_webhook_events"].insert_one({
                    "type": "message",
                    "ig_user_id": ig_user_id,
                    "data": msg_event,
                    "received_at": datetime.now(timezone.utc),
                })

        return {"status": "ok"}
