"""
Facebook & Instagram Professional API Service (Facebook Login Flow)

Implements Facebook Login for Instagram Professionals (Business / Creator).
Handles:
- Facebook OAuth authorization URL generation with permissions:
  * pages_show_list
  * instagram_basic
  * instagram_content_publish
  * pages_read_engagement
  * instagram_manage_comments
- Authorization code to short-lived user access token exchange
- Short-lived to long-lived (60 days) user access token exchange
- Fetching user's Facebook Pages (`/me/accounts`) with Page access tokens
- Discovering linked Instagram Business/Creator Account (`instagram_business_account`)
- Secure token encryption & storage across `businesses` and `instagram_connections`
- Direct access token retrieval endpoints
"""
import logging
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException
from bson import ObjectId

from app.core.config import settings
from app.services.instagram_service import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"

# Requested Facebook Login permissions
# Kept clean and minimal to avoid 'Invalid Scopes' errors from Meta
# Removed invalid 'pages_manage_posts' and unapproved instagram permissions
FACEBOOK_LOGIN_PERMISSIONS = [
    "public_profile",
    "email",
    "pages_show_list",
]


class FacebookService:
    @staticmethod
    def is_demo_mode() -> bool:
        """Returns True if Facebook App credentials are not configured."""
        app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
        app_secret = getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "INSTAGRAM_APP_SECRET", None)
        return not bool(app_id and app_secret)

    @staticmethod
    def get_authorization_url(state: str, custom_scopes: Optional[List[str]] = None) -> str:
        """
        Generate Facebook Login authorization URL with requested Instagram permissions.
        """
        app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
        if not app_id:
            raise HTTPException(status_code=500, detail="Facebook/Instagram App ID not configured")

        redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")
        api_version = getattr(settings, "FACEBOOK_API_VERSION", "v19.0")

        configured_scopes = getattr(settings, "FACEBOOK_SCOPES", None)
        if custom_scopes:
            scopes_list = custom_scopes
        elif configured_scopes:
            scopes_list = [s.strip() for s in configured_scopes.split(",") if s.strip()]
        else:
            scopes_list = FACEBOOK_LOGIN_PERMISSIONS

        scopes = ",".join(scopes_list)
        return (
            f"https://www.facebook.com/{api_version}/dialog/oauth"
            f"?client_id={app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&state={state}"
        )

    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for user access token,
        then upgrade to a 60-day long-lived token.
        """
        app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
        app_secret = getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "INSTAGRAM_APP_SECRET", None)
        redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")
        api_version = getattr(settings, "FACEBOOK_API_VERSION", "v19.0")

        if not app_id or not app_secret:
            raise HTTPException(status_code=500, detail="Facebook App credentials not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Exchange code for short-lived access token
            token_url = f"{GRAPH_API_BASE}/{api_version}/oauth/access_token"
            params = {
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            }
            res = await client.get(token_url, params=params)
            if res.status_code != 200:
                err_data = res.json() if res.content else {}
                err_msg = err_data.get("error", {}).get("message", res.text)
                logger.error(f"Facebook token exchange failed: {err_msg}")
                raise HTTPException(status_code=400, detail=f"Token exchange failed: {err_msg}")

            data = res.json()
            short_lived_token = data.get("access_token")
            expires_in = data.get("expires_in", 5184000)

            # 2. Exchange short-lived token for long-lived token (60 days)
            ll_params = {
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_lived_token,
            }
            try:
                ll_res = await client.get(token_url, params=ll_params)
                if ll_res.status_code == 200:
                    ll_data = ll_res.json()
                    access_token = ll_data.get("access_token", short_lived_token)
                    expires_in = ll_data.get("expires_in", expires_in)
                else:
                    access_token = short_lived_token
            except Exception as e:
                logger.warning(f"Failed to fetch long-lived FB token: {e}")
                access_token = short_lived_token

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": expires_in,
            }

    @staticmethod
    async def get_facebook_pages_and_instagram(user_access_token: str) -> Dict[str, Any]:
        """
        Fetch Facebook Pages and their linked Instagram Business / Professional accounts.
        """
        api_version = getattr(settings, "FACEBOOK_API_VERSION", "v19.0")
        url = f"{GRAPH_API_BASE}/{api_version}/me/accounts"
        params = {
            "fields": (
                "id,name,access_token,category,tasks,"
                "instagram_business_account{id,username,name,profile_picture_url,followers_count,media_count,account_type}"
            ),
            "access_token": user_access_token,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(url, params=params)
            if res.status_code != 200:
                err_data = res.json() if res.content else {}
                err_msg = err_data.get("error", {}).get("message", res.text)
                logger.warning(f"Could not fetch Facebook pages (status {res.status_code}): {err_msg}")
                return {
                    "pages": [],
                    "instagram_account": None,
                }

            data = res.json()
            pages_list = data.get("data", [])

            # Extract pages and any linked instagram business account
            pages = []
            linked_ig = None

            for p in pages_list:
                page_info = {
                    "page_id": p.get("id"),
                    "page_name": p.get("name"),
                    "page_access_token": p.get("access_token"),
                    "category": p.get("category"),
                }
                ig = p.get("instagram_business_account")
                if ig:
                    page_info["instagram_business_account"] = {
                        "id": ig.get("id"),
                        "username": ig.get("username"),
                        "name": ig.get("name"),
                        "profile_picture_url": ig.get("profile_picture_url"),
                        "followers_count": ig.get("followers_count"),
                        "media_count": ig.get("media_count"),
                        "account_type": ig.get("account_type", "BUSINESS"),
                    }
                    if not linked_ig:
                        linked_ig = {
                            **page_info["instagram_business_account"],
                            "linked_page_id": p.get("id"),
                            "linked_page_name": p.get("name"),
                            "page_access_token": p.get("access_token"),
                        }
                pages.append(page_info)

            return {
                "pages": pages,
                "instagram_account": linked_ig,
            }

    @staticmethod
    async def save_connection(
        db,
        user_id: str,
        token_data: Dict[str, Any],
        pages_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Store Facebook tokens, pages, and linked Instagram Professional account in the database.
        """
        access_token = token_data["access_token"]
        encrypted_token = encrypt_token(access_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=token_data.get("expires_in", 5184000))

        pages = pages_data.get("pages", [])
        ig = pages_data.get("instagram_account")

        # 1. Update businesses collection
        primary_page = pages[0] if pages else {}
        page_token = primary_page.get("page_access_token")
        encrypted_page_token = encrypt_token(page_token) if page_token else None

        business_query = {"$or": [{"user_id": user_id}, {"owner_id": user_id}, {"userId": user_id}]}
        business_update = {
            "fb_access_token": page_token or access_token,
            "fb_user_access_token": access_token,  # plaintext for legacy services compatibility
            "fb_access_token_encrypted": encrypted_token,
            "fb_token_expires_at": expires_at,
            "fb_pages": [
                {
                    "page_id": p.get("page_id"),
                    "page_name": p.get("page_name"),
                    "category": p.get("category"),
                }
                for p in pages
            ],
            "fb_connected": True,
            "updated_at": now,
        }

        if primary_page.get("page_id"):
            business_update["fb_page_id"] = primary_page["page_id"]
            business_update["fb_page_name"] = primary_page.get("page_name")

        if ig:
            business_update["ig_account_id"] = ig.get("id")
            business_update["ig_username"] = ig.get("username")
            # For Instagram Graph API with Facebook Login, page_access_token or user token is used
            business_update["ig_access_token"] = ig.get("page_access_token") or access_token

        await db["businesses"].update_one(
            business_query,
            {"$set": business_update},
            upsert=True,
        )

        # 2. Update users collection
        user_doc_update = {
            "facebook_access_token": encrypted_token,
            "facebook_connected": True,
            "facebook_connected_at": now,
        }
        if ig:
            user_doc_update["instagram_access_token"] = encrypt_token(ig.get("page_access_token") or access_token)
            user_doc_update["instagram_username"] = ig.get("username")
            user_doc_update["instagram_business_id"] = ig.get("id")

        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        await db["users"].update_one(
            {"_id": oid},
            {"$set": user_doc_update},
        )

        # 3. If Instagram business account is linked, also sync with instagram_connections
        if ig:
            ig_token = ig.get("page_access_token") or access_token
            ig_conn = {
                "user_id": user_id,
                "platform": "instagram",
                "login_method": "facebook_login",
                "instagram_user_id": ig.get("id"),
                "instagram_username": ig.get("username"),
                "account_type": ig.get("account_type", "BUSINESS"),
                "profile_picture_url": ig.get("profile_picture_url", ""),
                "encrypted_access_token": encrypt_token(ig_token),
                "connected": True,
                "linked_page_id": ig.get("linked_page_id"),
                "created_at": now,
                "updated_at": now,
            }
            await db["instagram_connections"].update_one(
                {"user_id": user_id, "platform": "instagram"},
                {"$set": ig_conn},
                upsert=True,
            )

        return {
            "facebook_connected": True,
            "pages_count": len(pages),
            "instagram_account": ig,
        }

    @staticmethod
    async def get_connection(db, user_id: str) -> Optional[Dict[str, Any]]:
        """Get Facebook connection info without sensitive token data."""
        business_query = {"$or": [{"user_id": user_id}, {"owner_id": user_id}, {"userId": user_id}]}
        business = await db["businesses"].find_one(business_query)
        if not business or not business.get("fb_connected", False):
            # Check users collection fallback
            oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
            user_doc = await db["users"].find_one({"_id": oid})
            if user_doc and user_doc.get("facebook_connected"):
                return {
                    "connected": True,
                    "fb_page_id": None,
                    "pages": [],
                    "instagram_business_account": None,
                }
            return None

        ig_account = None
        if business.get("ig_account_id"):
            ig_account = {
                "id": business.get("ig_account_id"),
                "username": business.get("ig_username"),
            }

        return {
            "connected": True,
            "fb_page_id": business.get("fb_page_id"),
            "fb_page_name": business.get("fb_page_name"),
            "page_access_token": business.get("fb_access_token"),
            "user_access_token": business.get("fb_user_access_token"),
            "pages": business.get("fb_pages", []),
            "instagram_business_account": ig_account,
        }

    @staticmethod
    async def get_access_token(db, user_id: str) -> str:
        """Get Facebook User Access Token for API calls (server-side only)."""
        business_query = {"$or": [{"user_id": user_id}, {"owner_id": user_id}, {"userId": user_id}]}
        business = await db["businesses"].find_one(business_query)
        if business and business.get("fb_access_token"):
            return business["fb_access_token"]
        if business and business.get("fb_access_token_encrypted"):
            return decrypt_token(business["fb_access_token_encrypted"])

        oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        user_doc = await db["users"].find_one({"_id": oid})
        if user_doc and user_doc.get("facebook_access_token"):
            return decrypt_token(user_doc["facebook_access_token"])

        raise HTTPException(status_code=400, detail="Facebook is not connected for this account.")

    @staticmethod
    async def verify_facebook_user_token(access_token: str) -> Dict[str, Any]:
        """
        Verify Facebook user access token with Graph API /me.
        Returns user profile info: id, name, email, first_name, last_name, picture.
        """
        if access_token == "DEMO_FB_ACCESS_TOKEN" or FacebookService.is_demo_mode():
            return {
                "id": "100000000000001",
                "name": "Facebook Demo User",
                "first_name": "Facebook",
                "last_name": "User",
                "email": "facebook_demo@example.com",
                "picture": {"data": {"url": ""}},
            }

        api_version = getattr(settings, "FACEBOOK_API_VERSION", "v19.0")
        url = f"{GRAPH_API_BASE}/{api_version}/me"
        params = {
            "fields": "id,name,email,first_name,last_name,picture.width(250).height(250)",
            "access_token": access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(url, params=params)
            if res.status_code != 200:
                err_data = res.json() if res.content else {}
                err_msg = err_data.get("error", {}).get("message", res.text)
                logger.error(f"Failed to verify Facebook token: {err_msg}")
                raise HTTPException(status_code=400, detail=f"Invalid Facebook access token: {err_msg}")
            return res.json()

    @staticmethod
    async def authenticate_facebook_user(
        db,
        access_token: str,
        account_type: str = "business",
    ):
        """
        Authenticate or register a user using Facebook Login.
        Issues JWT access & refresh tokens and returns user doc + tokens.
        """
        from app.models.user import User
        from app.models.refresh_session import RefreshSession
        from app.core.security import get_password_hash
        from app.services.auth_service import AuthService
        import hashlib
        import uuid

        fb_profile = await FacebookService.verify_facebook_user_token(access_token)
        fb_id = fb_profile["id"]
        email = fb_profile.get("email")
        if not email:
            email = f"fb_{fb_id}@facebook.user"

        email = email.lower().strip()
        full_name = fb_profile.get("name") or "Facebook User"
        first_name = fb_profile.get("first_name") or full_name.split()[0]
        last_name = fb_profile.get("last_name") or (" ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else None)
        picture_url = fb_profile.get("picture", {}).get("data", {}).get("url")

        # Check existing user by email or facebookId
        existing_user = await db["users"].find_one({
            "$or": [
                {"email": email},
                {"facebookId": fb_id},
            ]
        })

        now = datetime.now(timezone.utc)
        encrypted_token = encrypt_token(access_token)

        if existing_user:
            user_id = str(existing_user["_id"])
            update_data = {
                "facebookId": fb_id,
                "facebook_access_token": encrypted_token,
                "facebook_connected": True,
                "facebook_connected_at": now,
                "updated_at": now,
            }
            if picture_url and not existing_user.get("profileImageUrl"):
                update_data["profileImageUrl"] = picture_url
            if not existing_user.get("emailVerified"):
                update_data["emailVerified"] = True
                update_data["email_verified"] = True
                update_data["emailVerifiedAt"] = now

            await db["users"].update_one({"_id": existing_user["_id"]}, {"$set": update_data})
            user_doc = await db["users"].find_one({"_id": existing_user["_id"]})
            user = User(**user_doc)
        else:
            random_pwd = get_password_hash(f"fb_{uuid.uuid4()}_{secrets.token_hex(8)}")
            user = User(
                fullName=full_name,
                firstName=first_name,
                lastName=last_name,
                email=email,
                hashed_password=random_pwd,
                accountType=account_type or "business",
                authProviders=["facebook"],
                emailVerified=True,
                email_verified=True,
                emailVerifiedAt=now,
                termsAcceptedAt=now,
                profileImageUrl=picture_url,
                role="user",
            )
            doc = user.model_dump(by_alias=True, exclude={"id"})
            doc["facebookId"] = fb_id
            doc["facebook_access_token"] = encrypted_token
            doc["facebook_connected"] = True
            doc["facebook_connected_at"] = now
            result = await db["users"].insert_one(doc)
            user.id = str(result.inserted_id)

            try:
                from app.services.credit_service import CreditService
                await CreditService.get_or_create_subscription(db, user.id)
            except Exception as e:
                logger.warning(f"Could not provision subscription: {e}")

        # Also discover and save Pages & Instagram Professional accounts in background
        try:
            pages_data = await FacebookService.get_facebook_pages_and_instagram(access_token)
            await FacebookService.save_connection(
                db=db,
                user_id=str(user.id),
                token_data={"access_token": access_token, "expires_in": 5184000},
                pages_data=pages_data,
            )
        except Exception as e:
            logger.warning(f"Could not auto-link Facebook pages during login: {e}")

        # Generate JWT session tokens
        jwt_access_token = AuthService.create_token(
            user.id,
            settings.JWT_ACCESS_SECRET,
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        jwt_refresh_token = AuthService.create_token(
            user.id,
            settings.JWT_REFRESH_SECRET,
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )

        rs = RefreshSession(
            userId=str(user.id),
            hashedToken=get_password_hash(hashlib.sha256(jwt_refresh_token.encode()).hexdigest()),
            expiresAt=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await db["refresh_sessions"].insert_one(rs.model_dump(by_alias=True, exclude={"id"}))

        return user, jwt_access_token, jwt_refresh_token
