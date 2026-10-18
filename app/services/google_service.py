import hashlib, logging, secrets, httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException, status
from bson import ObjectId
from app.core.config import settings
from app.models.user import User
from app.models.refresh_session import RefreshSession
from app.services.auth_service import AuthService
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)

GOOGLE_AUTH_BASE = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

class GoogleService:
    @staticmethod
    def get_credentials() -> Tuple[Optional[str], Optional[str]]:
        import os
        cid = (
            settings.GOOGLE_CLIENT_ID
            or getattr(settings, 'google_client_id', None)
            or os.getenv('GOOGLE_CLIENT_ID')
            or os.getenv('NEXT_PUBLIC_GOOGLE_CLIENT_ID')
        )
        secret = (
            settings.GOOGLE_CLIENT_SECRET
            or getattr(settings, 'google_client_secret', None)
            or os.getenv('GOOGLE_CLIENT_SECRET')
        )
        return cid, secret

    @staticmethod
    def is_configured() -> bool:
        cid, secret = GoogleService.get_credentials()
        return bool(cid and secret)

    @staticmethod
    def get_authorization_url(redirect_uri: Optional[str] = None, state: Optional[str] = None) -> str:
        client_id, _ = GoogleService.get_credentials()
        if not client_id:
            raise HTTPException(status_code=500, detail='Google Client ID not configured. Please set GOOGLE_CLIENT_ID in server environment.')
        final_redirect = redirect_uri or settings.GOOGLE_REDIRECT_URI
        final_state = state or secrets.token_urlsafe(16)
        params = {
            'client_id': client_id,
            'redirect_uri': final_redirect,
            'response_type': 'code',
            'scope': 'openid email profile',
            'access_type': 'offline',
            'prompt': 'select_account',
            'state': final_state
        }
        import urllib.parse
        return f'{GOOGLE_AUTH_BASE}?' + urllib.parse.urlencode(params)

    @staticmethod
    async def exchange_code_for_token(code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        client_id, client_secret = GoogleService.get_credentials()
        final_redirect = (redirect_uri or settings.GOOGLE_REDIRECT_URI or "").strip()
        if final_redirect.endswith("/") and len(final_redirect) > 1:
            final_redirect = final_redirect.rstrip("/")

        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail='Google credentials not configured. Please add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your server environment variables.'
            )
        cleaned_code = (code or "").strip()
        payload = {
            'code': cleaned_code,
            'client_id': client_id.strip(),
            'client_secret': client_secret.strip(),
            'redirect_uri': final_redirect,
            'grant_type': 'authorization_code'
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
            if resp.status_code != 200:
                logger.error(f'Google token exchange failed ({resp.status_code}): {resp.text}')
                error_detail = "Failed to exchange Google code: Invalid or expired authorization code."
                try:
                    import json
                    err_json = resp.json()
                    err_type = err_json.get("error", "")
                    err_desc = err_json.get("error_description", "")
                    if err_type == "invalid_grant":
                        error_detail = "Failed to exchange Google code: Authorization code has expired or was already used. Please sign in again."
                    elif err_desc:
                        error_detail = f"Failed to exchange Google code: {err_desc}"
                    else:
                        error_detail = f"Failed to exchange Google code: {resp.text}"
                except Exception:
                    error_detail = f"Failed to exchange Google code: {resp.text}"
                raise HTTPException(status_code=400, detail=error_detail)
            return resp.json()

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        headers = {'Authorization': f'Bearer {access_token}'}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(GOOGLE_USERINFO_URL, headers=headers)
            if resp.status_code != 200:
                logger.error(f'Google userinfo failed ({resp.status_code}): {resp.text}')
                raise HTTPException(status_code=400, detail='Failed to retrieve Google profile.')
            return resp.json()

    @staticmethod
    async def authenticate_google_user(
        db,
        code: Optional[str] = None,
        access_token: Optional[str] = None,
        id_token: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        account_type: str = 'business',
        mode: str = 'login'
    ) -> Tuple[User, str, str]:
        user_info = None
        if code:
            token_data = await GoogleService.exchange_code_for_token(code, redirect_uri)
            access_token = token_data.get('access_token')
        if access_token:
            user_info = await GoogleService.get_user_info(access_token)
        elif id_token:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}')
                if r.status_code == 200:
                    user_info = r.json()
                else:
                    raise HTTPException(status_code=400, detail='Invalid Google ID Token.')

        if not user_info or not user_info.get('email'):
            raise HTTPException(status_code=400, detail='Unable to retrieve email from Google.')

        email = user_info['email'].lower().strip()
        google_id = user_info.get('sub')
        first_name = user_info.get('given_name') or user_info.get('name') or email.split('@')[0]
        last_name = user_info.get('family_name') or ''
        full_name = user_info.get('name') or f'{first_name} {last_name}'.strip()
        picture_url = user_info.get('picture')
        now = datetime.now(timezone.utc)

        # Normalize mode (login vs signup)
        auth_mode = (mode or 'login').lower().strip()

        # Check if user already exists in active users collection
        existing = await db['users'].find_one({'$or': [{'email': email}, {'googleId': google_id}]})

        if existing:
            # User exists in active users collection -> log them in
            user_id = str(existing['_id'])
            user = User.from_mongo(existing)
            update_data = {
                'googleId': google_id,
                'emailVerified': True,
                'email_verified': True,
                'emailVerifiedAt': existing.get('emailVerifiedAt') or now
            }
            if picture_url and not existing.get('profileImageUrl'):
                update_data['profileImageUrl'] = picture_url
            providers = existing.get('authProviders', [])
            if 'google' not in providers:
                providers.append('google')
                update_data['authProviders'] = providers

            await db['users'].update_one({'_id': ObjectId(user_id)}, {'$set': update_data})
            user.emailVerified = True
            user.email_verified = True
            user.id = user_id
        else:
            # Check if user exists in pending_users
            pending_existing = await db['pending_users'].find_one({'$or': [{'email': email}, {'googleId': google_id}]})
            if pending_existing:
                user_id = str(pending_existing['_id'])
                user = User.from_mongo(pending_existing)
                user.id = user_id
                user.onboardingCompleted = False
                p_update = {
                    'googleId': google_id,
                    'emailVerified': True,
                    'email_verified': True
                }
                if picture_url and not pending_existing.get('profileImageUrl'):
                    p_update['profileImageUrl'] = picture_url
                await db['pending_users'].update_one({'_id': ObjectId(user_id)}, {'$set': p_update})
            else:
                # Brand new user -> auto-register in pending_users for onboarding
                random_pwd = get_password_hash(secrets.token_urlsafe(32))
                user = User(
                    fullName=full_name,
                    name=full_name,
                    firstName=first_name,
                    lastName=last_name,
                    email=email,
                    hashed_password=random_pwd,
                    accountType=account_type or 'business',
                    authProviders=['google'],
                    emailVerified=True,
                    email_verified=True,
                    emailVerifiedAt=now,
                    termsAcceptedAt=now,
                    profileImageUrl=picture_url,
                    role='user',
                    onboardingCompleted=False,
                    onboarding_step=1
                )
                doc = user.model_dump(by_alias=True, exclude={'id'})
                doc['googleId'] = google_id
                doc['onboardingCompleted'] = False
                doc['onboarding_step'] = 1

                result = await db['pending_users'].insert_one(doc)
                user.id = str(result.inserted_id)

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
        await db['refresh_sessions'].insert_one(rs.model_dump(by_alias=True, exclude={'id'}))
        return user, jwt_access_token, jwt_refresh_token
