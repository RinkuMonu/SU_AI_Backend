import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import httpx
from bson import ObjectId
from fastapi import HTTPException, status

from app.core.config import settings
from app.services.instagram_service import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_BASE = "https://www.linkedin.com/oauth/v2"
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"

# Demo mode constants
DEMO_LI_AUTHOR_ID = "urn:li:person:demo_author_li_123"
DEMO_LI_DISPLAY_NAME = "Demo Business LinkedIn"


class LinkedInService:
    @staticmethod
    def is_configured() -> bool:
        """Check if LinkedIn OAuth credentials are fully configured."""
        client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None) or getattr(settings, "Linkedin_client_id", None)
        client_secret = getattr(settings, "LINKEDIN_CLIENT_SECRET", None) or getattr(settings, "Linkedin_client_secret", None)
        return bool(client_id and client_secret)

    @staticmethod
    def is_demo_mode() -> bool:
        """Check if LinkedIn API credentials are not configured."""
        return not LinkedInService.is_configured()

    @staticmethod
    def get_authorization_url(state: str) -> str:
        """Generate official LinkedIn OAuth 2.0 authorization URL."""
        client_id = getattr(settings, "LINKEDIN_CLIENT_ID", None) or getattr(settings, "Linkedin_client_id", None)
        redirect_uri = getattr(settings, "LINKEDIN_REDIRECT_URI", "https://dhandagrow.com/login/user")
        scope = getattr(settings, "LINKEDIN_SCOPES", "openid profile email w_member_social")

        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LinkedIn integration is not configured. Missing LINKEDIN_CLIENT_ID."
            )

        return (
            f"{LINKEDIN_AUTH_BASE}/authorization"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&state={state}"
            f"&scope={scope}"
        )


    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token via LinkedIn OAuth token endpoint."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
            "client_id": settings.LINKEDIN_CLIENT_ID,
            "client_secret": settings.LINKEDIN_CLIENT_SECRET,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.post(f"{LINKEDIN_AUTH_BASE}/accessToken", data=data, headers=headers)
                if res.status_code != 200:
                    err_json = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
                    logger.error(f"LinkedIn token exchange failed: {res.text}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"LinkedIn token exchange failed: {err_json.get('error_description', res.text)}"
                    )
                return res.json()
            except httpx.HTTPError as e:
                logger.error(f"LinkedIn HTTP error during token exchange: {e}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to communicate with LinkedIn authorization server"
                )

    @staticmethod
    async def get_linkedin_profile(access_token: str) -> Dict[str, Any]:
        """Fetch member identity via LinkedIn UserInfo API."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.get(f"{LINKEDIN_API_BASE}/userinfo", headers=headers)
                if res.status_code != 200:
                    logger.error(f"LinkedIn userinfo failed: {res.text}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to retrieve LinkedIn member profile"
                    )
                return res.json()
            except httpx.HTTPError as e:
                logger.error(f"LinkedIn profile fetch HTTP error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to communicate with LinkedIn API"
                )

    @staticmethod
    async def save_connection(
        db,
        user_id: str,
        token_data: Dict[str, Any],
        profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Persist encrypted LinkedIn connection in DB and sync business record."""
        now = datetime.now(timezone.utc)
        sub_id = profile.get("sub") or profile.get("id") or "unknown"
        author_id = f"urn:li:person:{sub_id}" if not str(sub_id).startswith("urn:li:") else sub_id
        display_name = profile.get("name") or profile.get("localizedFirstName", "LinkedIn User")

        expires_in = token_data.get("expires_in")
        expires_at = now + timedelta(seconds=expires_in) if expires_in else None

        access_token = token_data.get("access_token", "")
        encrypted = encrypt_token(access_token) if access_token else None

        connection_doc = {
            "user_id": user_id,
            "platform": "linkedin",
            "linkedin_author_id": author_id,
            "display_name": display_name,
            "account_type": "PROFILE",
            "profile_picture_url": profile.get("picture", ""),
            "encrypted_access_token": encrypted,
            "token_expires_at": expires_at,
            "scopes": token_data.get("scope", "").split(),
            "connected": True,
            "created_at": now,
            "updated_at": now,
        }

        await db["linkedin_connections"].update_one(
            {"user_id": user_id, "platform": "linkedin"},
            {"$set": connection_doc},
            upsert=True
        )

        # Sync to businesses collection for publishing compatibility
        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "linkedin_author_id": author_id,
                "linkedin_access_token": access_token,
                "linkedin_account_name": display_name,
                "updated_at": now
            }}
        )

        return connection_doc

    @staticmethod
    async def get_connection(db, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve active LinkedIn connection for user (without exposing decrypted tokens)."""
        return await db["linkedin_connections"].find_one(
            {"user_id": user_id, "platform": "linkedin", "connected": True}
        )

    @staticmethod
    async def get_decrypted_token(db, user_id: str) -> str:
        """Retrieve decrypted LinkedIn access token for backend publishing."""
        conn = await db["linkedin_connections"].find_one(
            {"user_id": user_id, "platform": "linkedin", "connected": True}
        )
        if not conn:
            raise HTTPException(status_code=400, detail="LinkedIn is not connected")

        encrypted = conn.get("encrypted_access_token")
        if not encrypted:
            raise HTTPException(status_code=400, detail="LinkedIn access token not found")

        try:
            return decrypt_token(encrypted)
        except Exception as e:
            logger.error(f"LinkedIn token decryption failed for user {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to decrypt LinkedIn token. Please reconnect.")

    @staticmethod
    async def disconnect(db, user_id: str) -> bool:
        """Disconnect LinkedIn account and invalidate stored credentials."""
        now = datetime.now(timezone.utc)
        result = await db["linkedin_connections"].update_one(
            {"user_id": user_id, "platform": "linkedin"},
            {"$set": {
                "connected": False,
                "encrypted_access_token": None,
                "updated_at": now
            }}
        )

        await db["businesses"].update_one(
            {"owner_id": user_id},
            {"$set": {
                "linkedin_author_id": None,
                "linkedin_access_token": None,
                "linkedin_account_name": None,
                "updated_at": now
            }}
        )

        return result.modified_count > 0

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
        if not linkedin_author_id or not linkedin_access_token:
            conn = await db["linkedin_connections"].find_one({"user_id": user_id, "connected": True})
            if conn:
                linkedin_author_id = linkedin_author_id or conn.get("linkedin_author_id") or conn.get("author_id")
                enc = conn.get("encrypted_access_token")
                if enc:
                    try:
                        linkedin_access_token = linkedin_access_token or decrypt_token(enc)
                    except Exception:
                        pass
                linkedin_access_token = linkedin_access_token or conn.get("access_token")

                
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
