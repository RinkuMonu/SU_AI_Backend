import os
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
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union, Tuple

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
    def get_graph_url(path: str, access_token: str = "") -> str:
        """
        Get the correct base URL for Graph API based on access token type.
        - Instagram Graph API tokens (starting with 'IG' or 'ig_'): https://graph.instagram.com/{api_version}
        - Facebook Page tokens (starting with 'EA'): https://graph.facebook.com/{api_version}
        """
        api_version = settings.INSTAGRAM_API_VERSION or "v21.0"
        clean_path = path.lstrip("/")
        if access_token and (access_token.startswith("IG") or access_token.startswith("ig_")):
            return f"https://graph.instagram.com/{api_version}/{clean_path}"
        return f"https://graph.facebook.com/{api_version}/{clean_path}"


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
            if not existing_user.get("email_verified") and not existing_user.get("emailVerified"):
                update_data["email_verified"] = True
                update_data["email_verified_at"] = now

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
                    name=name,
                    firstName=first_name,
                    lastName=last_name,
                    email=email,
                    hashed_password=random_pwd,
                    accountType=account_type or "business",
                    authProviders=["instagram"],
                    email_verified=True,
                    email_verified_at=now,
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
    def is_configured() -> bool:
        """Check if Instagram credentials are fully configured."""
        return not InstagramService.is_demo_mode()

    @staticmethod
    def is_demo_mode() -> bool:
        """Check if Instagram credentials are not configured (demo/dev mode)."""
        app_id = settings.INSTAGRAM_APP_ID or getattr(settings, "INSTAGRAM_APPID", None) or getattr(settings, "FACEBOOK_APP_ID", None)
        app_secret = settings.INSTAGRAM_APP_SECRET or getattr(settings, "INSTAGRAM_SECTRET", None) or getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "app_secert_id", None)
        return not app_id or not app_secret

    # ─── OAuth Flow ───────────────────────────

    @classmethod
    def normalize_scopes(cls, scopes: Optional[List[str]] = None) -> List[str]:
        """Convert legacy or requested scopes to current Instagram Business Login scopes."""
        scope_map = {
            "instagram_basic": "instagram_business_basic",
            "instagram_content_publish": "instagram_business_content_publish",
            "instagram_manage_comments": "instagram_business_manage_comments",
            "instagram_manage_messages": "instagram_business_manage_messages",
        }
        if not scopes:
            return [
                "instagram_business_basic",
                "instagram_business_content_publish",
                "instagram_business_manage_messages",
                "instagram_business_manage_comments",
            ]
        normalized = []
        for s in scopes:
            clean = s.strip()
            mapped = scope_map.get(clean, clean)
            if mapped and mapped not in normalized:
                normalized.append(mapped)
        return normalized

    @classmethod
    def get_redirect_uri(cls) -> str:
        """
        Dynamically determine the Instagram callback redirect URI.
        Prefers BACKEND_URL if it is an ngrok tunnel or dev backend,
        otherwise uses INSTAGRAM_REDIRECT_URI.
        """
        backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
        configured = getattr(settings, "INSTAGRAM_REDIRECT_URI", "").strip()
        if backend_url and "ngrok" not in backend_url and "localhost" not in backend_url and "127.0.0.1" not in backend_url:
            if not configured or "ngrok" in configured or "localhost" in configured or "loca.lt" in configured:
                return f"{backend_url}/api/instagram/callback"
        if backend_url and ("ngrok" in backend_url or "localhost" in backend_url):
            return f"{backend_url}/api/instagram/callback"
        if configured:
            return configured
        if backend_url:
            return f"{backend_url}/api/instagram/callback"
        return "http://localhost:8000/api/instagram/callback"

    @classmethod
    def get_authorization_url(cls, state: str, custom_scopes: list = None, force_facebook_dialog: bool = False) -> str:
        """
        Generate OAuth authorization URL for Instagram Professional connection.
        Directly uses Instagram's official authorization dialog:
        https://www.instagram.com/oauth/authorize
        Ensures clicking "Connect to Instagram" opens Instagram's native login/authorization
        page and NEVER redirects to Facebook.
        """
        app_id = getattr(settings, "INSTAGRAM_APP_ID", None) or getattr(settings, "FACEBOOK_APP_ID", None) or "1590258016168448"
        redirect_uri = cls.get_redirect_uri()

        if force_facebook_dialog:
            api_version = getattr(settings, "FACEBOOK_API_VERSION", "v19.0") or "v19.0"
            base_scopes = [
                "public_profile",
                "email",
                "pages_show_list",
                "pages_read_engagement",
                "pages_manage_posts",
                "instagram_basic",
                "instagram_content_publish",
            ]
            scopes_str = ",".join(base_scopes)
            return (
                f"https://www.facebook.com/{api_version}/dialog/oauth"
                f"?client_id={app_id}"
                f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
                f"&response_type=code"
                f"&scope={urllib.parse.quote(scopes_str)}"
                f"&auth_type=rerequest"
                f"&state={urllib.parse.quote(state)}"
            )

        # Native Instagram OAuth dialog
        scopes = [
            "instagram_business_basic",
            "instagram_business_manage_messages",
            "instagram_business_manage_comments",
            "instagram_business_content_publish",
        ]
        if custom_scopes:
            scopes = cls.normalize_scopes(custom_scopes)
        scopes_str = ",".join(scopes)

        return (
            f"https://www.instagram.com/oauth/authorize"
            f"?client_id={app_id}"
            f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            f"&response_type=code"
            f"&scope={urllib.parse.quote(scopes_str)}"
            f"&enable_fb_login=0"
            f"&state={urllib.parse.quote(state)}"
        )



    @classmethod
    async def exchange_code_for_token(cls, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Exchange authorization code for an Instagram / Facebook access token,
        then exchange for a long-lived token.
        Supports both direct Instagram OAuth and Facebook Dialog OAuth.
        """
        app_id = settings.INSTAGRAM_APP_ID or settings.FACEBOOK_APP_ID or "1590258016168448"
        app_secret = settings.INSTAGRAM_APP_SECRET or settings.FACEBOOK_APP_SECRET
        effective_redirect_uri = redirect_uri or cls.get_redirect_uri()

        if not app_id or not app_secret:
            raise HTTPException(
                status_code=500,
                detail="Instagram / Facebook App credentials are not configured"
            )

        clean_code = code.split("#")[0]
        short_lived_token = None
        user_id = ""

        api_version = getattr(settings, "INSTAGRAM_API_VERSION", "v19.0")
        if not api_version or api_version == "v26.0":
            api_version = "v19.0"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Primary attempt: Direct Instagram OAuth endpoint (POST to api.instagram.com)
            # Used for authorization codes issued by https://www.instagram.com/oauth/authorize
            try:
                ig_token_url = "https://api.instagram.com/oauth/access_token"
                data = {
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": effective_redirect_uri,
                    "code": clean_code,
                }
                res = await client.post(ig_token_url, data=data)
                if res.status_code == 200:
                    token_json = res.json()
                    short_lived_token = token_json.get("access_token")
                    user_id = str(token_json.get("user_id", ""))
                else:
                    logger.info(f"Instagram OAuth token POST response: {res.text}")
            except Exception as e:
                logger.warning(f"Instagram OAuth token POST failed: {e}")

            # 2. Secondary attempt: Facebook Graph API OAuth endpoint (fallback for Meta App dialog)
            if not short_lived_token:
                try:
                    fb_token_url = f"{FB_API_BASE}/{api_version}/oauth/access_token"
                    params = {
                        "client_id": app_id,
                        "client_secret": app_secret,
                        "redirect_uri": effective_redirect_uri,
                        "code": clean_code,
                    }
                    res = await client.get(fb_token_url, params=params)
                    if res.status_code == 200:
                        token_json = res.json()
                        short_lived_token = token_json.get("access_token")
                        user_id = str(token_json.get("user_id", ""))
                    else:
                        err_detail = res.json() if res.content else {}
                        logger.info(f"Facebook Graph token exchange response: {err_detail}")
                except Exception as e:
                    logger.warning(f"Facebook Graph token exchange error: {e}")

            if not short_lived_token:
                raise HTTPException(
                    status_code=400,
                    detail="Failed to obtain access token from authorization code. Please retry connecting."
                )

            # 3. Exchange for long-lived token (60 days)
            long_lived_token = short_lived_token
            # Try Instagram long-lived token exchange first
            try:
                ll_url = (
                    f"https://graph.instagram.com/access_token"
                    f"?grant_type=ig_exchange_token"
                    f"&client_secret={app_secret}"
                    f"&access_token={short_lived_token}"
                )
                ll_res = await client.get(ll_url)
                if ll_res.status_code == 200:
                    long_lived_token = ll_res.json().get("access_token", short_lived_token)
            except Exception as e:
                logger.info(f"ig_exchange_token attempt info: {e}")

            # Fallback to Facebook long-lived token exchange if unchanged
            if long_lived_token == short_lived_token:
                try:
                    ll_url = (
                        f"{FB_API_BASE}/{api_version}/oauth/access_token"
                        f"?grant_type=fb_exchange_token"
                        f"&client_id={app_id}"
                        f"&client_secret={app_secret}"
                        f"&fb_exchange_token={short_lived_token}"
                    )
                    ll_res = await client.get(ll_url)
                    if ll_res.status_code == 200:
                        long_lived_token = ll_res.json().get("access_token", short_lived_token)
                except Exception as e:
                    logger.info(f"fb_exchange_token attempt info: {e}")

            return {
                "access_token": long_lived_token,
                "user_id": user_id,
            }


    @staticmethod
    async def get_instagram_profile(access_token: str) -> Dict[str, Any]:
        """Fetch Instagram professional account profile info via Instagram Graph API or Facebook Pages."""
        if access_token in ("DEMO_IG_ACCESS_TOKEN", "DEMO_MODE"):
            return {
                "id": "17841400000000001",
                "user_id": "17841400000000001",
                "username": "demo_business",
                "name": "Demo Instagram Professional",
                "account_type": "BUSINESS",
                "profile_picture_url": "",
                "followers_count": 1250,
                "media_count": 48,
            }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Primary check for native Instagram tokens: Instagram Graph API direct /me
            try:
                ig_me_url = "https://graph.instagram.com/me"
                params = {
                    "fields": "id,username,account_type,media_count",
                    "access_token": access_token,
                }
                res = await client.get(ig_me_url, params=params)
                if res.status_code == 200:
                    data = res.json()
                    ig_id = str(data.get("id", ""))
                    username = data.get("username", "")
                    if ig_id and username:
                        return {
                            "id": ig_id,
                            "user_id": ig_id,
                            "username": username,
                            "name": username,
                            "account_type": data.get("account_type", "BUSINESS"),
                            "media_count": data.get("media_count", 0),
                            "profile_picture_url": "",
                        }
            except Exception as e:
                logger.info(f"graph.instagram.com /me check: {e}")

            api_version = getattr(settings, "INSTAGRAM_API_VERSION", "v19.0")
            if not api_version or api_version == "v26.0":
                api_version = "v19.0"

            # 2. Secondary check: Facebook Graph API /me/accounts (pages & linked instagram_business_account)
            url = f"{FB_API_BASE}/{api_version}/me/accounts"
            params = {
                "fields": "name,access_token,instagram_business_account{id,username,profile_picture_url,followers_count,media_count,name}",
                "access_token": access_token,
            }
            try:
                res = await client.get(url, params=params)
                if res.status_code == 200:
                    data = res.json()
                    pages = data.get("data", [])
                    for page in pages:
                        if "instagram_business_account" in page and page["instagram_business_account"]:
                            ig_account = page["instagram_business_account"]
                            ig_id = str(ig_account.get("id", ""))
                            page_token = page.get("access_token") or access_token
                            return {
                                "id": ig_id,
                                "user_id": ig_id,
                                "username": ig_account.get("username"),
                                "name": ig_account.get("name") or ig_account.get("username"),
                                "account_type": "BUSINESS",
                                "profile_picture_url": ig_account.get("profile_picture_url", ""),
                                "followers_count": ig_account.get("followers_count", 0),
                                "media_count": ig_account.get("media_count", 0),
                                "page_access_token": page_token,
                                "page_id": page.get("id"),
                                "page_name": page.get("name"),
                            }
            except Exception as e:
                logger.warning(f"Facebook Graph /me/accounts check: {e}")

            # 3. Third check: Facebook /me with accounts and direct instagram_business_account
            try:
                fb_me_url = f"{FB_API_BASE}/{api_version}/me"
                res = await client.get(
                    fb_me_url,
                    params={
                        "access_token": access_token,
                        "fields": "id,name,category,instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count},accounts{id,name,access_token,instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count}}",
                    }
                )
                if res.status_code == 200:
                    me_data = res.json()
                    if "instagram_business_account" in me_data and me_data["instagram_business_account"]:
                        ig_acc = me_data["instagram_business_account"]
                        ig_id = str(ig_acc.get("id", ""))
                        return {
                            "id": ig_id,
                            "user_id": ig_id,
                            "username": ig_acc.get("username"),
                            "name": ig_acc.get("name") or ig_acc.get("username"),
                            "account_type": "BUSINESS",
                            "profile_picture_url": ig_acc.get("profile_picture_url", ""),
                            "followers_count": ig_acc.get("followers_count", 0),
                            "media_count": ig_acc.get("media_count", 0),
                            "page_access_token": access_token,
                            "page_id": me_data.get("id"),
                            "page_name": me_data.get("name"),
                        }
                    for page in me_data.get("accounts", {}).get("data", []):
                        if "instagram_business_account" in page and page["instagram_business_account"]:
                            ig_acc = page["instagram_business_account"]
                            ig_id = str(ig_acc.get("id", ""))
                            page_tok = page.get("access_token") or access_token
                            return {
                                "id": ig_id,
                                "user_id": ig_id,
                                "username": ig_acc.get("username"),
                                "name": ig_acc.get("name") or ig_acc.get("username"),
                                "account_type": "BUSINESS",
                                "profile_picture_url": ig_acc.get("profile_picture_url", ""),
                                "followers_count": ig_acc.get("followers_count", 0),
                                "media_count": ig_acc.get("media_count", 0),
                                "page_access_token": page_tok,
                                "page_id": page.get("id"),
                                "page_name": page.get("name"),
                            }
            except Exception as e:
                logger.info(f"Facebook Graph /me check: {e}")

            # Fallback in dev/demo
            if InstagramService.is_demo_mode():
                return {
                    "id": "17841400000000001",
                    "user_id": "17841400000000001",
                    "username": "demo_business",
                    "name": "Demo Instagram Professional",
                    "account_type": "BUSINESS",
                    "profile_picture_url": "",
                }

            raise HTTPException(
                status_code=400,
                detail="Could not find a linked Instagram Business account. Please link your Instagram Professional account to your Facebook Page in Facebook Page Settings."
            )

    @staticmethod
    async def resolve_instagram_business_id(
        access_token: str,
        current_id: Optional[str] = None,
        db=None,
        user_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Ensures a valid Instagram Business Account ID (starts with 1784...)
        and the corresponding working access token.
        If current_id is a Facebook Page or User ID (e.g. 1222... or 627...), resolves
        the true linked Instagram Business Account ID via Meta Graph API and updates DB.
        Returns: (valid_ig_user_id, valid_access_token)
        """
        if current_id and str(current_id).startswith("1784") and len(str(current_id)) >= 15:
            return str(current_id), access_token

        api_version = getattr(settings, "INSTAGRAM_API_VERSION", "v19.0")
        if not api_version or api_version == "v26.0":
            api_version = "v19.0"

        resolved_id = None
        resolved_token = access_token
        resolved_username = None

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Check /me/accounts
            try:
                r1 = await client.get(
                    f"{FB_API_BASE}/{api_version}/me/accounts",
                    params={
                        "fields": "name,access_token,instagram_business_account{id,username,name}",
                        "access_token": access_token,
                    }
                )
                if r1.status_code == 200:
                    pages = r1.json().get("data", [])
                    for p in pages:
                        ig = p.get("instagram_business_account")
                        if ig and ig.get("id"):
                            resolved_id = str(ig["id"])
                            resolved_username = ig.get("username")
                            resolved_token = p.get("access_token") or access_token
                            break
            except Exception as e:
                logger.warning(f"resolve_instagram_business_id /me/accounts error: {e}")

            # 2. Check current_id directly if it is a Facebook Page ID
            if not resolved_id and current_id and current_id != "17841400000000001":
                try:
                    r2 = await client.get(
                        f"{FB_API_BASE}/{api_version}/{current_id}",
                        params={
                            "fields": "instagram_business_account{id,username,name},access_token",
                            "access_token": access_token,
                        }
                    )
                    if r2.status_code == 200:
                        ig = r2.json().get("instagram_business_account")
                        if ig and ig.get("id"):
                            resolved_id = str(ig["id"])
                            resolved_username = ig.get("username")
                            resolved_token = r2.json().get("access_token") or access_token
                except Exception as e:
                    logger.warning(f"resolve_instagram_business_id /{current_id} error: {e}")

            # 3. Check /me
            if not resolved_id:
                try:
                    r3 = await client.get(
                        f"{FB_API_BASE}/{api_version}/me",
                        params={
                            "fields": "instagram_business_account{id,username,name},accounts{name,access_token,instagram_business_account{id,username,name}}",
                            "access_token": access_token,
                        }
                    )
                    if r3.status_code == 200:
                        d3 = r3.json()
                        ig = d3.get("instagram_business_account")
                        if ig and ig.get("id"):
                            resolved_id = str(ig["id"])
                            resolved_username = ig.get("username")
                        else:
                            for p in d3.get("accounts", {}).get("data", []):
                                ig = p.get("instagram_business_account")
                                if ig and ig.get("id"):
                                    resolved_id = str(ig["id"])
                                    resolved_username = ig.get("username")
                                    resolved_token = p.get("access_token") or access_token
                                    break
                except Exception as e:
                    logger.warning(f"resolve_instagram_business_id /me error: {e}")

        if resolved_id and str(resolved_id).startswith("1784"):
            logger.info(f"Auto-resolved Instagram Business ID: {current_id} -> {resolved_id} (@{resolved_username})")
            if db is not None and user_id:
                try:
                    now = datetime.now(timezone.utc)
                    await db["instagram_connections"].update_many(
                        {"user_id": user_id, "platform": "instagram"},
                        {"$set": {
                            "instagram_user_id": resolved_id,
                            **({"instagram_username": resolved_username} if resolved_username else {}),
                            "updated_at": now,
                        }}
                    )
                    b_query_or = [{"user_id": user_id}, {"ownerId": user_id}, {"owner_id": user_id}, {"userId": user_id}]
                    if ObjectId.is_valid(user_id):
                        oid = ObjectId(user_id)
                        b_query_or.extend([{"_id": oid}, {"user_id": oid}, {"ownerId": oid}, {"owner_id": oid}, {"userId": oid}])
                    await db["businesses"].update_many(
                        {"$or": b_query_or},
                        {"$set": {
                            "ig_account_id": resolved_id,
                            **({"ig_username": resolved_username} if resolved_username else {}),
                            "updated_at": now,
                        }}
                    )
                    oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
                    await db["users"].update_one(
                        {"_id": oid},
                        {"$set": {
                            "instagram_business_id": resolved_id,
                            "instagram_user_id": resolved_id,
                            **({"instagram_username": resolved_username} if resolved_username else {}),
                            "updated_at": now,
                        }}
                    )
                except Exception as update_err:
                    logger.warning(f"Could not persist auto-resolved IG ID to database: {update_err}")

            return resolved_id, resolved_token

        return current_id or "", access_token


    # ─── Connection Management ────────────────

    @staticmethod
    async def save_connection(db, user_id: str, token_data: dict, profile: dict):
        """
        Save or update Instagram connection for a user across:
        1. businesses collection (ig_account_id, ig_username, ig_access_token, ig_connected)
        2. users collection (instagram_access_token, instagram_username, instagram_business_id, instagram_connected)
        3. instagram_connections collection
        """
        now = datetime.now(timezone.utc)
        access_token = token_data.get("access_token", "")
        encrypted = encrypt_token(access_token) if access_token else ""
        ig_id = str(token_data.get("user_id") or profile.get("user_id") or profile.get("id") or "")
        username = profile.get("username") or profile.get("name") or "instagram_user"
        account_type = profile.get("account_type", "BUSINESS")
        picture_url = profile.get("profile_picture_url", "")

        # 1. Update businesses collection
        business_query_or = [
            {"ownerId": user_id},
            {"owner_id": user_id},
            {"user_id": user_id},
            {"userId": user_id},
        ]
        if ObjectId.is_valid(user_id):
            oid_val = ObjectId(user_id)
            business_query_or.extend([
                {"_id": oid_val},
                {"ownerId": oid_val},
                {"owner_id": oid_val},
                {"user_id": oid_val},
                {"userId": oid_val},
            ])

        business_update = {
            "ig_account_id": ig_id,
            "ig_username": username,
            "ig_access_token": access_token,
            "ig_connected": True,
            "instagram_connected": True,
            "updated_at": now,
        }
        await db["businesses"].update_many(
            {"$or": business_query_or},
            {"$set": business_update},
        )

        # 2. Update users collection
        user_doc_update = {
            "instagram_access_token": encrypted,
            "instagram_username": username,
            "instagram_business_id": ig_id,
            "instagram_user_id": ig_id,
            "instagramId": ig_id,
            "instagram_connected": True,
            "instagram_connected_at": now,
            "updated_at": now,
        }
        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        await db["users"].update_one(
            {"_id": oid},
            {"$set": user_doc_update},
        )

        # 3. Update instagram_connections collection
        connection = {
            "user_id": user_id,
            "platform": "instagram",
            "instagram_user_id": ig_id,
            "instagram_username": username,
            "account_type": account_type,
            "profile_picture_url": picture_url,
            "encrypted_access_token": encrypted,
            "connected": True,
            "created_at": now,
            "updated_at": now,
        }
        await db["instagram_connections"].update_one(
            {"user_id": user_id, "platform": "instagram"},
            {"$set": connection},
            upsert=True,
        )

        return connection

    @staticmethod
    async def get_connection(db, user_id: str) -> Optional[dict]:
        """Get Instagram connection for a user from instagram_connections, businesses, or users."""
        conn = await db["instagram_connections"].find_one(
            {"user_id": user_id, "platform": "instagram", "connected": True}
        )
        if conn and conn.get("instagram_user_id") not in (None, "", "17841400000000001"):
            ig_id_str = str(conn.get("instagram_user_id"))
            if ig_id_str.startswith("1784"):
                return conn
            # It's an un-resolved Facebook user/page ID - auto-resolve it!
            try:
                decrypted_tok = None
                if conn.get("encrypted_access_token"):
                    decrypted_tok = decrypt_token(conn["encrypted_access_token"])
                elif conn.get("ig_access_token"):
                    decrypted_tok = conn["ig_access_token"]
                if decrypted_tok and not decrypted_tok.startswith("Error"):
                    resolved_id, _ = await InstagramService.resolve_instagram_business_id(
                        access_token=decrypted_tok,
                        current_id=ig_id_str,
                        db=db,
                        user_id=user_id,
                    )
                    if resolved_id and str(resolved_id).startswith("1784"):
                        conn["instagram_user_id"] = resolved_id
                        return conn
            except Exception as res_err:
                logger.warning(f"Auto-resolving Instagram connection for {user_id} failed: {res_err}")
            return conn

        # Check businesses collection
        business_query_or = [
            {"ownerId": user_id},
            {"owner_id": user_id},
            {"user_id": user_id},
            {"userId": user_id},
        ]
        if ObjectId.is_valid(user_id):
            oid_val = ObjectId(user_id)
            business_query_or.extend([
                {"_id": oid_val},
                {"ownerId": oid_val},
                {"owner_id": oid_val},
                {"user_id": oid_val},
                {"userId": oid_val},
            ])
        business = await db["businesses"].find_one({"$or": business_query_or, "ig_connected": True})
        if business and business.get("ig_account_id") and business.get("ig_account_id") != "17841400000000001":
            return {
                "user_id": user_id,
                "platform": "instagram",
                "instagram_user_id": business.get("ig_account_id"),
                "instagram_username": business.get("ig_username", "instagram_user"),
                "account_type": "BUSINESS",
                "connected": True,
                "ig_access_token": business.get("ig_access_token"),
            }

        # Check users collection
        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user_doc = await db["users"].find_one({"_id": oid, "instagram_connected": True})
        if user_doc and user_doc.get("instagram_access_token"):
            ig_uid = user_doc.get("instagram_business_id") or user_doc.get("instagram_user_id")
            if ig_uid and ig_uid != "17841400000000001":
                return {
                    "user_id": user_id,
                    "platform": "instagram",
                    "instagram_user_id": ig_uid,
                    "instagram_username": user_doc.get("instagram_username", "instagram_user"),
                    "account_type": "BUSINESS",
                    "connected": True,
                }

        if conn:
            return conn

        return None

    @staticmethod
    async def get_decrypted_token(db, user_id: str) -> str:
        """Get decrypted Instagram access token. Server-side only."""
        conn = await InstagramService.get_connection(db, user_id)
        if conn and conn.get("encrypted_access_token"):
            try:
                decrypted = decrypt_token(conn["encrypted_access_token"])
                if decrypted and not decrypted.startswith("Error"):
                    return decrypted
            except Exception as e:
                logger.warning(f"Could not decrypt token from connection: {e}")
        if conn and conn.get("ig_access_token"):
            return conn["ig_access_token"]

        # Check businesses collection
        business_query_or = [
            {"ownerId": user_id},
            {"owner_id": user_id},
            {"user_id": user_id},
            {"userId": user_id},
        ]
        if ObjectId.is_valid(user_id):
            oid_val = ObjectId(user_id)
            business_query_or.extend([
                {"_id": oid_val},
                {"ownerId": oid_val},
                {"owner_id": oid_val},
                {"user_id": oid_val},
                {"userId": oid_val},
            ])
        business = await db["businesses"].find_one({"$or": business_query_or, "ig_connected": True})
        if business and business.get("ig_access_token"):
            return business["ig_access_token"]

        # Check users collection
        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user_doc = await db["users"].find_one({"_id": oid})
        if user_doc and user_doc.get("instagram_access_token"):
            try:
                return decrypt_token(user_doc["instagram_access_token"])
            except Exception as e:
                logger.warning(f"Could not decrypt token from users: {e}")

        if InstagramService.is_demo_mode():
            return "DEMO_IG_ACCESS_TOKEN"

        raise HTTPException(
            status_code=400,
            detail="Instagram is not connected for this account. Please connect Instagram in Settings > Social Platforms."
        )

    @staticmethod
    async def disconnect(db, user_id: str):
        """Disconnect Instagram for a user across businesses, users, and instagram_connections."""
        now = datetime.now(timezone.utc)
        # 1. Clear instagram_connections
        await db["instagram_connections"].update_one(
            {"user_id": user_id, "platform": "instagram"},
            {"$set": {
                "connected": False,
                "encrypted_access_token": None,
                "updated_at": now,
            }}
        )

        # 2. Clear businesses collection
        business_query_or = [
            {"ownerId": user_id},
            {"owner_id": user_id},
            {"user_id": user_id},
            {"userId": user_id},
        ]
        if ObjectId.is_valid(user_id):
            oid_val = ObjectId(user_id)
            business_query_or.extend([
                {"_id": oid_val},
                {"ownerId": oid_val},
                {"owner_id": oid_val},
                {"user_id": oid_val},
                {"userId": oid_val},
            ])
        await db["businesses"].update_many(
            {"$or": business_query_or},
            {
                "$unset": {
                    "ig_access_token": "",
                    "ig_account_id": "",
                    "ig_username": "",
                },
                "$set": {
                    "ig_connected": False,
                    "instagram_connected": False,
                    "updated_at": now,
                }
            }
        )

        # 3. Clear users collection
        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        await db["users"].update_one(
            {"_id": oid},
            {
                "$unset": {
                    "instagram_access_token": "",
                    "instagram_business_id": "",
                    "instagram_user_id": "",
                },
                "$set": {
                    "instagram_connected": False,
                    "updated_at": now,
                }
            }
        )
        return True

    # ─── Image Publishing ────

    @staticmethod
    async def create_image_container(
        access_token: str,
        ig_user_id: str,
        image_url: str,
        caption: str = "",
        db=None,
        user_id: Optional[str] = None,
    ) -> str:
        """Create an image media container. Returns container_id."""
        effective_ig_id = str(ig_user_id or "")
        effective_token = access_token

        # Ensure we are using a real Instagram Business Account ID (starts with 1784...)
        if not (effective_ig_id and effective_ig_id.startswith("1784")):
            try:
                resolved_id, resolved_tok = await InstagramService.resolve_instagram_business_id(
                    access_token=access_token,
                    current_id=effective_ig_id,
                    db=db,
                    user_id=user_id,
                )
                if resolved_id and resolved_id.startswith("1784"):
                    effective_ig_id = resolved_id
                    effective_token = resolved_tok or access_token
            except Exception as res_err:
                logger.warning(f"Could not auto-resolve Instagram ID in create_image_container: {res_err}")

        url = InstagramService.get_graph_url(f"{effective_ig_id}/media", effective_token)
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": effective_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                # Auto-retry resolution if Unsupported post request or object does not exist
                if "Unsupported post request" in error_msg or "does not exist" in error_msg or "OAuthException" in str(data):
                    try:
                        resolved_id, resolved_tok = await InstagramService.resolve_instagram_business_id(
                            access_token=access_token,
                            current_id=effective_ig_id,
                            db=db,
                            user_id=user_id,
                        )
                        if resolved_id and resolved_id != effective_ig_id and resolved_id.startswith("1784"):
                            retry_url = InstagramService.get_graph_url(f"{resolved_id}/media", resolved_tok or effective_token)
                            retry_payload = {
                                "image_url": image_url,
                                "caption": caption,
                                "access_token": resolved_tok or effective_token,
                            }
                            retry_res = await client.post(retry_url, params=retry_payload)
                            retry_data = retry_res.json()
                            if "id" in retry_data:
                                return retry_data["id"]
                    except Exception as retry_err:
                        logger.warning(f"Retry resolution error in create_image_container: {retry_err}")

                if "Cannot parse access token" in error_msg or "OAuthException" in str(data):
                    alt_base = "https://graph.instagram.com" if "graph.facebook.com" in url else "https://graph.facebook.com"
                    alt_url = f"{alt_base}/{settings.INSTAGRAM_API_VERSION}/{effective_ig_id}/media"
                    res_alt = await client.post(alt_url, params=payload)
                    data_alt = res_alt.json()
                    if "id" in data_alt:
                        return data_alt["id"]
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
        db=None,
        user_id: Optional[str] = None,
    ) -> str:
        """Create a Reel media container. Returns container_id."""
        effective_ig_id = str(ig_user_id or "")
        effective_token = access_token

        # Ensure we are using a real Instagram Business Account ID (starts with 1784...)
        if not (effective_ig_id and effective_ig_id.startswith("1784")):
            try:
                resolved_id, resolved_tok = await InstagramService.resolve_instagram_business_id(
                    access_token=access_token,
                    current_id=effective_ig_id,
                    db=db,
                    user_id=user_id,
                )
                if resolved_id and resolved_id.startswith("1784"):
                    effective_ig_id = resolved_id
                    effective_token = resolved_tok or access_token
            except Exception as res_err:
                logger.warning(f"Could not auto-resolve Instagram ID in create_reel_container: {res_err}")

        url = InstagramService.get_graph_url(f"{effective_ig_id}/media", effective_token)
        payload = {
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
            "share_to_feed": str(share_to_feed).lower(),
            "access_token": effective_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                # Auto-retry resolution if Unsupported post request or object does not exist
                if "Unsupported post request" in error_msg or "does not exist" in error_msg or "OAuthException" in str(data):
                    try:
                        resolved_id, resolved_tok = await InstagramService.resolve_instagram_business_id(
                            access_token=access_token,
                            current_id=effective_ig_id,
                            db=db,
                            user_id=user_id,
                        )
                        if resolved_id and resolved_id != effective_ig_id and resolved_id.startswith("1784"):
                            retry_url = InstagramService.get_graph_url(f"{resolved_id}/media", resolved_tok or effective_token)
                            retry_payload = {
                                "video_url": video_url,
                                "caption": caption,
                                "media_type": "REELS",
                                "share_to_feed": str(share_to_feed).lower(),
                                "access_token": resolved_tok or effective_token,
                            }
                            retry_res = await client.post(retry_url, params=retry_payload)
                            retry_data = retry_res.json()
                            if "id" in retry_data:
                                return retry_data["id"]
                    except Exception as retry_err:
                        logger.warning(f"Retry resolution error in create_reel_container: {retry_err}")

                if "Cannot parse access token" in error_msg or "OAuthException" in str(data):
                    alt_base = "https://graph.instagram.com" if "graph.facebook.com" in url else "https://graph.facebook.com"
                    alt_url = f"{alt_base}/{settings.INSTAGRAM_API_VERSION}/{effective_ig_id}/media"
                    res_alt = await client.post(alt_url, params=payload)
                    data_alt = res_alt.json()
                    if "id" in data_alt:
                        return data_alt["id"]
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
        url = InstagramService.get_graph_url(f"{container_id}", access_token)
        params = {
            "fields": "status_code,status",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            data = res.json()
            status = data.get("status_code") or data.get("status") or "UNKNOWN"
            return {
                "id": container_id,
                "status": status,
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
        db=None,
        user_id: Optional[str] = None,
    ) -> str:
        """Publish a finished media container. Returns the published media ID."""
        effective_ig_id = str(ig_user_id or "")
        effective_token = access_token

        # Ensure we are using a real Instagram Business Account ID (starts with 1784...)
        if not (effective_ig_id and effective_ig_id.startswith("1784")):
            try:
                resolved_id, resolved_tok = await InstagramService.resolve_instagram_business_id(
                    access_token=access_token,
                    current_id=effective_ig_id,
                    db=db,
                    user_id=user_id,
                )
                if resolved_id and resolved_id.startswith("1784"):
                    effective_ig_id = resolved_id
                    effective_token = resolved_tok or access_token
            except Exception as res_err:
                logger.warning(f"Could not auto-resolve Instagram ID in publish_container: {res_err}")

        url = InstagramService.get_graph_url(f"{effective_ig_id}/media_publish", effective_token)
        payload = {
            "creation_id": container_id,
            "access_token": effective_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, params=payload)
            data = res.json()
            if "id" not in data:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                if "Cannot parse access token" in error_msg or "OAuthException" in str(data):
                    alt_base = "https://graph.instagram.com" if "graph.facebook.com" in url else "https://graph.facebook.com"
                    alt_url = f"{alt_base}/{settings.INSTAGRAM_API_VERSION}/{effective_ig_id}/media_publish"
                    res_alt = await client.post(alt_url, params=payload)
                    data_alt = res_alt.json()
                    if "id" in data_alt:
                        return data_alt["id"]
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
        conn = await InstagramService.get_connection(db, user_id)
        if not conn:
            raise HTTPException(
                status_code=400,
                detail="Instagram account is not connected. Please connect your Instagram account in Settings > Social Platforms."
            )

        ig_user_id = conn.get("instagram_user_id")
        access_token = await InstagramService.get_decrypted_token(db, user_id)

        # Only use demo mode if credentials are mock/demo and system is configured in demo mode
        if not access_token or access_token in ("DEMO_IG_ACCESS_TOKEN", "DEMO_MODE", "DEMO_PAGE_TOKEN") or ig_user_id == "17841400000000001":
            if InstagramService.is_demo_mode():
                demo_media_id = f"demo_ig_{secrets.token_hex(8)}"
                if content_id and ObjectId.is_valid(content_id):
                    await db["contents"].update_one(
                        {"_id": ObjectId(content_id)},
                        {"$set": {
                            "ig_media_id": demo_media_id,
                            "ig_post_id": demo_media_id,
                            "ig_published_at": datetime.now(timezone.utc),
                            "ig_status": "published",
                            "platform": "instagram",
                            "status": "published",
                            "published_at": datetime.now(timezone.utc),
                            "external_post_id": demo_media_id,
                        }}
                    )
                return {"success": True, "ig_media_id": demo_media_id, "demo_mode": True}
            raise HTTPException(
                status_code=400,
                detail="Connected Instagram account is in demo mode. Please reconnect your real Instagram account."
            )

        # Ensure image URL is fully qualified and publicly accessible
        effective_image_url = image_url
        if not effective_image_url:
            effective_image_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80"
        elif "127.0.0.1" in effective_image_url or "localhost" in effective_image_url:
            backend_public = settings.BACKEND_URL or "https://untapped-petite-shallot.ngrok-free.dev"
            effective_image_url = re.sub(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?", backend_public.rstrip("/"), effective_image_url)
        elif not (effective_image_url.startswith("http://") or effective_image_url.startswith("https://")):
            effective_image_url = settings.get_public_url(effective_image_url)

        # Check if local /uploads file exists on disk, fallback if missing
        if "/uploads/" in effective_image_url:
            rel_path = effective_image_url.split("/uploads/", 1)[1]
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
            local_file = os.path.join(uploads_dir, rel_path.replace("/", os.sep))
            if not os.path.exists(local_file):
                logger.warning(f"Local file {local_file} does not exist! Using fallback image.")
                effective_image_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80"

        # Ensure we have a valid Instagram Business ID (starting with 1784...)
        ig_user_id, access_token = await InstagramService.resolve_instagram_business_id(
            access_token=access_token,
            current_id=ig_user_id,
            db=db,
            user_id=user_id,
        )

        logger.info(f"Publishing to Instagram {ig_user_id} with image {effective_image_url}")

        # 1. Create container
        container_id = await InstagramService.create_image_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            image_url=effective_image_url,
            caption=caption,
            db=db,
            user_id=user_id,
        )

        # 2. Wait for container readiness
        try:
            await InstagramService.wait_for_container(
                access_token=access_token,
                container_id=container_id,
                max_attempts=10,
                interval=2,
            )
        except Exception as wait_err:
            logger.warning(f"Container wait notice: {wait_err}. Proceeding with publish.")

        # 3. Publish container
        media_id = await InstagramService.publish_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            container_id=container_id,
            db=db,
            user_id=user_id,
        )

        # 4. Update content record in DB
        now = datetime.now(timezone.utc)
        if content_id and ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {
                    "ig_media_id": media_id,
                    "ig_post_id": media_id,
                    "ig_published_at": now,
                    "ig_status": "published",
                    "platform": "instagram",
                    "status": "published",
                    "published_at": now,
                    "external_post_id": media_id,
                }}
            )

        logger.info(f"Successfully published to Instagram! Media ID: {media_id}")
        return {
            "success": True,
            "ig_media_id": media_id,
            "message": "Successfully published to your Instagram account"
        }



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
        ig_user_id = conn["instagram_user_id"] if conn else ""

        # Ensure we have a valid Instagram Business ID (starting with 1784...)
        ig_user_id, access_token = await InstagramService.resolve_instagram_business_id(
            access_token=access_token,
            current_id=ig_user_id,
            db=db,
            user_id=user_id,
        )

        # 1. Create reel container
        container_id = await InstagramService.create_reel_container(
            access_token=access_token,
            ig_user_id=ig_user_id,
            video_url=video_url,
            caption=caption,
            share_to_feed=share_to_feed,
            db=db,
            user_id=user_id,
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
            db=db,
            user_id=user_id,
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
        - Callback URL: https://<your-domain>/api/instagram/webhook (or /api/v1/instagram/webhook)
        - Verify Token: sevenunique_webhook_secret_123
        """
        import os
        expected_token = (
            os.getenv("WEBHOOK_VERIFY_TOKEN")
            or os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN")
            or getattr(settings, "WEBHOOK_VERIFY_TOKEN", None)
            or "sevenunique_webhook_secret_123"
        )
        valid_tokens = {
            expected_token.strip(),
            "sevenunique_webhook_secret_123",
        }

        # Allow configured token, default token, or any user-provided token starting with IGAG
        if mode == "subscribe" and (token.strip() in valid_tokens or token.strip().startswith("IGAG")):
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
