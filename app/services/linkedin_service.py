import hashlib
import logging
import secrets
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

import httpx
from bson import ObjectId
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.user import User
from app.models.refresh_session import RefreshSession
from app.core.security import get_password_hash
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


class LinkedInService:
    @staticmethod
    def is_configured() -> bool:
        client_id = settings.LINKEDIN_CLIENT_ID or getattr(settings, "Linkedin_client_id", None)
        client_secret = settings.LINKEDIN_CLIENT_SECRET or getattr(settings, "Linkedin_client_secret", None)
        return bool(client_id and client_secret)

    @staticmethod
    def is_demo_mode() -> bool:
        """Returns True if LinkedIn App credentials are not configured."""
        return not LinkedInService.is_configured()

    @staticmethod
    def get_authorization_url(
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
        mode: str = "login"
    ) -> str:
        """Construct LinkedIn OAuth 2.0 authorization URL."""
        client_id = settings.LINKEDIN_CLIENT_ID or getattr(settings, "Linkedin_client_id", None)
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LinkedIn Client ID not configured in server settings."
            )

        default_redirect = f"{settings.FRONTEND_URL.rstrip('/')}/login/user" if settings.FRONTEND_URL else "http://localhost:3000/login/user"
        configured_redirect = settings.LINKEDIN_REDIRECT_URI
        if configured_redirect and settings.FRONTEND_URL and settings.FRONTEND_URL.startswith("https://") and "localhost" in configured_redirect:
            configured_redirect = default_redirect

        final_redirect = redirect_uri or configured_redirect or default_redirect
        effective_state = state or f"{mode}_linkedin_{secrets.token_urlsafe(16)}"
        scopes = settings.LINKEDIN_SCOPES or "openid profile email w_member_social"

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": final_redirect,
            "state": effective_state,
            "scope": scopes,
        }
        return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def exchange_code_for_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """Exchange authorization code for LinkedIn access token."""
        client_id = settings.LINKEDIN_CLIENT_ID or getattr(settings, "Linkedin_client_id", None)
        client_secret = settings.LINKEDIN_CLIENT_SECRET or getattr(settings, "Linkedin_client_secret", None)
        default_redirect = f"{settings.FRONTEND_URL.rstrip('/')}/login/user" if settings.FRONTEND_URL else "http://localhost:3000/login/user"
        configured_redirect = settings.LINKEDIN_REDIRECT_URI
        if configured_redirect and settings.FRONTEND_URL and settings.FRONTEND_URL.startswith("https://") and "localhost" in configured_redirect:
            configured_redirect = default_redirect

        final_redirect = redirect_uri or configured_redirect or default_redirect

        if not client_id or not client_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LinkedIn credentials not configured."
            )

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": final_redirect,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(LINKEDIN_TOKEN_URL, data=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"LinkedIn token exchange failed ({resp.status_code}): {resp.text}")
                err_detail = resp.text
                try:
                    err_json = resp.json()
                    err_detail = err_json.get("error_description") or err_json.get("error") or err_detail
                except Exception:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to exchange LinkedIn code: {err_detail}"
                )
            return resp.json()

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        """Fetch user profile from LinkedIn OpenID UserInfo endpoint with propagation delay retry."""
        import asyncio
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(3):
                resp = await client.get(LINKEDIN_USERINFO_URL, headers=headers)
                if resp.status_code == 200:
                    return resp.json()

                # If token was freshly generated, LinkedIn propagation delay might trigger REVOKED_ACCESS_TOKEN
                if resp.status_code == 401 and "REVOKED_ACCESS_TOKEN" in resp.text and attempt < 2:
                    logger.warning(f"LinkedIn token propagation delay detected on userinfo (attempt {attempt+1}/3). Retrying in 1.5s...")
                    await asyncio.sleep(1.5)
                    continue

                logger.warning(f"LinkedIn userinfo endpoint failed ({resp.status_code}): {resp.text}. Trying fallback /v2/me.")
                break

            # Fallback to legacy /v2/me if openid is not available
            fallback_resp = await client.get("https://api.linkedin.com/v2/me", headers=headers)
            if fallback_resp.status_code == 200:
                data = fallback_resp.json()
                sub = data.get("id")
                first = data.get("localizedFirstName") or "LinkedIn"
                last = data.get("localizedLastName") or "User"
                return {
                    "sub": sub,
                    "name": f"{first} {last}".strip(),
                    "given_name": first,
                    "family_name": last,
                    "email": f"linkedin_{sub}@linkedin.user",
                }

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to retrieve LinkedIn user profile."
            )

    @staticmethod
    async def authenticate_linkedin_user(
        db,
        code: Optional[str] = None,
        access_token: Optional[str] = None,
        id_token: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        account_type: str = "business",
        mode: str = "login"
    ) -> Tuple[User, str, str]:
        """
        Authenticate or register a user via LinkedIn OAuth.
        Returns (user, access_token_jwt, refresh_token_jwt).
        """
        token_data = {}
        if code:
            token_data = await LinkedInService.exchange_code_for_token(code, redirect_uri)
            access_token = token_data.get("access_token")
            if not id_token:
                id_token = token_data.get("id_token")

        if not access_token and not id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing LinkedIn access token or authorization code."
            )

        user_info: Dict[str, Any] = {}

        # 1. Prefer decoding id_token (Standard OpenID Connect JWT)
        # It contains sub, name, email, picture, and completely bypasses LinkedIn's token propagation delay on /v2/userinfo
        if id_token:
            try:
                import jwt
                decoded = jwt.decode(id_token, options={"verify_signature": False})
                if decoded.get("sub") or decoded.get("email"):
                    user_info = decoded
                    logger.info(f"Successfully extracted LinkedIn user info from id_token for sub={decoded.get('sub')}")
            except Exception as e:
                logger.warning(f"Failed to decode LinkedIn id_token: {e}")

        # 2. Fallback to querying userinfo API endpoint if id_token was absent or couldn't be decoded
        if not user_info and access_token:
            user_info = await LinkedInService.get_user_info(access_token)

        email = (user_info.get("email") or "").lower().strip()
        linkedin_id = str(user_info.get("sub") or "")

        if not email and not linkedin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to retrieve identity from LinkedIn."
            )

        if not email:
            email = f"linkedin_{linkedin_id}@linkedin.user"

        first_name = user_info.get("given_name") or user_info.get("name") or email.split("@")[0]
        last_name = user_info.get("family_name") or ""
        full_name = user_info.get("name") or f"{first_name} {last_name}".strip()
        picture_url = user_info.get("picture")
        author_urn = f"urn:li:person:{linkedin_id}" if linkedin_id else ""
        now = datetime.now(timezone.utc)
        auth_mode = (mode or "login").lower().strip()

        # Check existing user by email or linkedinId
        existing = await db["users"].find_one({
            "$or": [
                {"email": email},
                {"linkedinId": linkedin_id},
                {"linkedin_id": linkedin_id},
            ]
        })

        if existing:
            user_id = str(existing["_id"])
            update_data = {
                "linkedinId": linkedin_id,
                "linkedin_id": linkedin_id,
                "linkedin_access_token": access_token,
                "linkedin_author_id": author_urn,
                "linkedin_connected": True,
                "emailVerified": True,
                "email_verified": True,
                "emailVerifiedAt": existing.get("emailVerifiedAt") or now,
                "updated_at": now,
            }
            if picture_url and not existing.get("profileImageUrl"):
                update_data["profileImageUrl"] = picture_url
            providers = existing.get("authProviders", [])
            if "linkedin" not in providers:
                providers.append("linkedin")
                update_data["authProviders"] = providers

            await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
            user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
            user = User.from_mongo(user_doc)
            user.id = user_id
            user.emailVerified = True
            user.email_verified = True
            user.onboardingCompleted = bool(existing.get("onboardingCompleted", False))
            user.onboarding_step = existing.get("onboarding_step", 1)

        else:
            # Check pending_users
            pending_existing = await db["pending_users"].find_one({
                "$or": [
                    {"email": email},
                    {"linkedinId": linkedin_id},
                    {"linkedin_id": linkedin_id},
                ]
            })

            if pending_existing:
                user_id = str(pending_existing["_id"])
                user = User.from_mongo(pending_existing)
                user.id = user_id
                user.onboardingCompleted = False
                user.onboarding_step = pending_existing.get("onboarding_step", 1)
            else:
                # Create NEW user
                random_pwd = get_password_hash(secrets.token_urlsafe(32))
                user = User(
                    fullName=full_name,
                    name=full_name,
                    firstName=first_name,
                    lastName=last_name,
                    email=email,
                    hashed_password=random_pwd,
                    accountType=account_type or "business",
                    authProviders=["linkedin"],
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
                doc["linkedinId"] = linkedin_id
                doc["linkedin_id"] = linkedin_id
                doc["linkedin_access_token"] = access_token
                doc["linkedin_author_id"] = author_urn
                doc["linkedin_connected"] = True
                doc["onboardingCompleted"] = False
                doc["onboarding_completed"] = False
                doc["onboarding_step"] = 1

                # If signup mode, keep in pending_users until onboarding, otherwise insert to users
                result = await db["users"].insert_one(doc)
                user.id = str(result.inserted_id)

                try:
                    from app.services.credit_service import CreditService
                    await CreditService.get_or_create_subscription(db, user.id)
                except Exception as e:
                    logger.warning(f"Could not provision credits for LinkedIn user: {e}")

        # Update businesses collection with linkedin_author_id and linkedin_access_token
        try:
            business_query_or = [
                {"ownerId": str(user.id)},
                {"owner_id": str(user.id)},
                {"user_id": str(user.id)},
                {"userId": str(user.id)},
            ]
            if ObjectId.is_valid(str(user.id)):
                oid_val = ObjectId(str(user.id))
                business_query_or.extend([
                    {"_id": oid_val},
                    {"ownerId": oid_val},
                    {"owner_id": oid_val},
                    {"user_id": oid_val},
                    {"userId": oid_val},
                ])
            existing_biz = await db["businesses"].find_one({"$or": business_query_or})
            if existing_biz:
                await db["businesses"].update_many(
                    {"$or": business_query_or},
                    {"$set": {
                        "linkedin_author_id": author_urn,
                        "linkedin_access_token": access_token,
                        "linkedin_connected": True,
                        "updated_at": now,
                    }}
                )
            else:
                biz_name = getattr(user, "businessName", None) or f"{user.fullName}'s Business"
                await db["businesses"].insert_one({
                    "ownerId": str(user.id),
                    "owner_id": str(user.id),
                    "userId": str(user.id),
                    "user_id": str(user.id),
                    "businessName": biz_name,
                    "business_name": biz_name,
                    "businessType": "Retail",
                    "industry": "General",
                    "email": email,
                    "linkedin_author_id": author_urn,
                    "linkedin_access_token": access_token,
                    "linkedin_connected": True,
                    "created_at": now,
                    "updated_at": now,
                })
        except Exception as b_err:
            logger.warning(f"Could not sync LinkedIn to businesses: {b_err}")

        # Save connection record in linkedin_connections
        try:
            conn_doc = {
                "user_id": str(user.id),
                "platform": "linkedin",
                "linkedin_id": linkedin_id,
                "author_id": author_urn,
                "access_token": access_token,
                "name": full_name,
                "email": email,
                "connected": True,
                "updated_at": now,
            }
            await db["linkedin_connections"].update_one(
                {"user_id": str(user.id)},
                {"$set": conn_doc},
                upsert=True
            )
        except Exception as c_err:
            logger.warning(f"Could not save linkedin_connections record: {c_err}")

        # Generate JWT session tokens
        jwt_access_token = AuthService.create_token(
            user.id, settings.JWT_ACCESS_SECRET, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        jwt_refresh_token = AuthService.create_token(
            user.id, settings.JWT_REFRESH_SECRET, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        rs = RefreshSession(
            userId=str(user.id),
            hashedToken=get_password_hash(hashlib.sha256(jwt_refresh_token.encode()).hexdigest()),
            expiresAt=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        await db["refresh_sessions"].insert_one(rs.model_dump(by_alias=True, exclude={"id"}))

        return user, jwt_access_token, jwt_refresh_token

    @staticmethod
    async def publish_post(
        db,
        user_id: str,
        caption: str = "",
        image_url: Optional[str] = None,
        content_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publish a post (text or article/image) to connected LinkedIn profile.
        This performs REAL publishing - no simulation/dummy posts.
        """
        now = datetime.now(timezone.utc)
        
        # 1. Resolve business or user document
        business = None
        if business_id and ObjectId.is_valid(business_id):
            business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
            
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
            
        if not business or not business.get("linkedin_author_id") or not business.get("linkedin_access_token"):
            business = await db["businesses"].find_one({"$or": business_query_or})
            
        linkedin_author_id = business.get("linkedin_author_id") if business else None
        linkedin_access_token = business.get("linkedin_access_token") if business else None
        
        # Fallback to users collection
        if not linkedin_author_id or not linkedin_access_token:
            u_oid = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
            user_doc = await db["users"].find_one({"_id": u_oid})
            if user_doc:
                linkedin_author_id = linkedin_author_id or user_doc.get("linkedin_author_id")
                linkedin_access_token = linkedin_access_token or user_doc.get("linkedin_access_token")
                
        # Fallback to linkedin_connections
        if not linkedin_author_id or not linkedin_access_token:
            conn = await db["linkedin_connections"].find_one({"user_id": user_id})
            if conn:
                linkedin_author_id = linkedin_author_id or conn.get("author_id")
                linkedin_access_token = linkedin_access_token or conn.get("access_token")
                
        if not linkedin_author_id or not linkedin_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LinkedIn is not connected. Please connect LinkedIn in Settings > Social Platforms or Login with LinkedIn."
            )
            
        # Ensure author URN format
        author_urn = linkedin_author_id
        if not author_urn.startswith("urn:li:"):
            author_urn = f"urn:li:person:{author_urn}"
            
        full_caption = caption.strip() if caption else "Shared via DhandaGrow AI"
        
        # --- Attempt 1: Use the newer REST Posts API (recommended by LinkedIn) ---
        post_id = None
        post_url = None
        
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                rest_payload = {
                    "author": author_urn,
                    "commentary": full_caption,
                    "visibility": "PUBLIC",
                    "distribution": {
                        "feedDistribution": "MAIN_FEED",
                        "targetEntities": [],
                        "thirdPartyDistributionChannels": []
                    },
                    "lifecycleState": "PUBLISHED",
                    "isReshareDisabledByAuthor": False
                }
                
                # Add media if image_url provided and is a valid public URL
                if image_url and (str(image_url).startswith("http://") or str(image_url).startswith("https://")) and not ("localhost" in str(image_url) or "127.0.0.1" in str(image_url)):
                    rest_payload["content"] = {
                        "article": {
                            "source": str(image_url),
                            "title": full_caption[:200] if full_caption else "Post from DhandaGrow AI"
                        }
                    }
                
                rest_headers = {
                    "Authorization": f"Bearer {linkedin_access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                    "LinkedIn-Version": "202401",
                    "Content-Type": "application/json"
                }
                
                res = await client.post(
                    "https://api.linkedin.com/rest/posts",
                    headers=rest_headers,
                    json=rest_payload
                )
                
                if res.status_code in [200, 201]:
                    post_id = res.headers.get("x-restli-id") or res.headers.get("x-linkedin-id")
                    if not post_id:
                        try:
                            res_data = res.json()
                            post_id = res_data.get("id", f"li_{int(now.timestamp())}")
                        except Exception:
                            post_id = f"li_{int(now.timestamp())}"
                    post_url = f"https://www.linkedin.com/feed/update/{post_id}"
                    logger.info(f"LinkedIn post published successfully via REST API: {post_id}")
                else:
                    err_json = {}
                    try:
                        err_json = res.json()
                    except Exception:
                        pass
                    err_msg = err_json.get("message") or res.text
                    logger.warning(f"LinkedIn REST Posts API error ({res.status_code}): {err_msg}")
                    
                    # Check for token issues
                    if res.status_code == 401 or "REVOKED_ACCESS_TOKEN" in str(err_msg) or "EXPIRED" in str(err_msg).upper():
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Your LinkedIn access token has expired or been revoked. Please re-connect LinkedIn in Settings > Social Platforms > LinkedIn to get a new token."
                        )
                    
                    # If REST API failed for other reasons, try UGC API
                    logger.info("Trying UGC Posts API as fallback...")
                    
                    share_content = {
                        "shareCommentary": {"text": full_caption},
                        "shareMediaCategory": "NONE"
                    }
                    
                    if image_url and (str(image_url).startswith("http://") or str(image_url).startswith("https://")) and not ("localhost" in str(image_url) or "127.0.0.1" in str(image_url)):
                        share_content["shareMediaCategory"] = "ARTICLE"
                        share_content["media"] = [{"status": "READY", "originalUrl": str(image_url)}]
                    
                    ugc_payload = {
                        "author": author_urn,
                        "lifecycleState": "PUBLISHED",
                        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
                        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
                    }
                    
                    ugc_headers = {
                        "Authorization": f"Bearer {linkedin_access_token}",
                        "X-Restli-Protocol-Version": "2.0.0",
                        "Content-Type": "application/json"
                    }
                    
                    res2 = await client.post("https://api.linkedin.com/v2/ugcPosts", headers=ugc_headers, json=ugc_payload)
                    
                    if res2.status_code in [200, 201]:
                        res_data = res2.json()
                        post_id = res_data.get("id") or f"li_{int(now.timestamp())}"
                        post_url = f"https://www.linkedin.com/feed/update/{post_id}"
                        logger.info(f"LinkedIn post published via UGC API: {post_id}")
                    else:
                        err_json2 = {}
                        try:
                            err_json2 = res2.json()
                        except Exception:
                            pass
                        err_msg2 = err_json2.get("message") or res2.text
                        
                        if res2.status_code == 401 or "REVOKED_ACCESS_TOKEN" in str(err_msg2) or "EXPIRED" in str(err_msg2).upper():
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Your LinkedIn access token has expired or been revoked. Please re-connect LinkedIn in Settings > Social Platforms > LinkedIn to get a new token."
                            )
                        
                        if res2.status_code == 403 or "ACCESS_DENIED" in str(err_msg2):
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"LinkedIn denied publishing access. Your LinkedIn app may need the 'w_member_social' permission. Error: {err_msg2}"
                            )
                        
                        raise HTTPException(
                            status_code=res2.status_code,
                            detail=f"LinkedIn publishing error: {err_msg2}"
                        )
                        
        except HTTPException:
            raise
        except Exception as net_err:
            logger.error(f"Network error communicating with LinkedIn: {net_err}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to LinkedIn API: {str(net_err)}. Please try again later."
            )
            
        # Update content status if content_id provided
        if content_id and ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {
                    "linkedin_post_id": post_id,
                    "linkedin_published_at": now,
                    "linkedin_status": "published",
                    "status": "published",
                    "published_at": now,
                }}
            )
            
        return {
            "success": True,
            "message": "Successfully published to LinkedIn feed!",
            "post_id": post_id,
            "url": post_url,
            "data": {
                "post_id": post_id,
                "author": author_urn,
                "url": post_url
            }
        }
