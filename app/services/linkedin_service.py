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
    def is_demo_mode() -> bool:
        """Check if LinkedIn API credentials are not configured."""
        return not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_SECRET

    @staticmethod
    def get_authorization_url(state: str) -> str:
        """Generate official LinkedIn OAuth 2.0 authorization URL."""
        client_id = settings.LINKEDIN_CLIENT_ID
        redirect_uri = settings.LINKEDIN_REDIRECT_URI
        scope = "openid profile email w_member_social"

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
