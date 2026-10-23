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
        final_redirect = redirect_uri or settings.GOOGLE_REDIRECT_URI
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=500,
                detail='Google credentials not configured. Please add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your server environment variables.'
            )
        payload = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': final_redirect,
            'grant_type': 'authorization_code'
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=payload)
            if resp.status_code != 200:
                logger.error(f'Google token exchange failed ({resp.status_code}): {resp.text}')
                raise HTTPException(status_code=400, detail=f'Failed to exchange Google code: {resp.text}')
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
        mode: str = 'login',
        phone_number: Optional[str] = None,
        country_code: Optional[str] = None
    ) -> Tuple[User, str, str]:
        user_info = None
        client_id, _ = GoogleService.get_credentials()

        if code:
            token_data = await GoogleService.exchange_code_for_token(code, redirect_uri)
            access_token = token_data.get('access_token')
            if not id_token and token_data.get('id_token'):
                id_token = token_data.get('id_token')

        if access_token:
            user_info = await GoogleService.get_user_info(access_token)
        elif id_token:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}')
                if r.status_code == 200:
                    user_info = r.json()
                    # Validate Google ID Token issuer and audience
                    token_iss = user_info.get('iss', '')
                    if token_iss not in ['accounts.google.com', 'https://accounts.google.com']:
                        raise HTTPException(status_code=400, detail='Invalid Google ID Token issuer.')
                    if client_id and user_info.get('aud') and user_info.get('aud') != client_id:
                        logger.warning(f"Google ID token audience mismatch: {user_info.get('aud')} vs {client_id}")
                else:
                    raise HTTPException(status_code=400, detail='Invalid Google ID Token.')

        if not user_info or not user_info.get('email'):
            raise HTTPException(status_code=400, detail='Unable to retrieve verified email from Google.')

        email = user_info['email'].lower().strip()
        google_id = user_info.get('sub')
        first_name = user_info.get('given_name') or user_info.get('name') or email.split('@')[0]
        last_name = user_info.get('family_name') or ''
        full_name = user_info.get('name') or f'{first_name} {last_name}'.strip()
        picture_url = user_info.get('picture')
        now = datetime.now(timezone.utc)

        # Normalize phone number if supplied by user during registration
        norm_phone = None
        if phone_number and str(phone_number).strip():
            from app.utils.phone import normalize_phone_number, InvalidPhoneNumberException
            try:
                norm_phone = normalize_phone_number(str(phone_number).strip(), country_code=country_code)
            except InvalidPhoneNumberException as e:
                raise HTTPException(status_code=400, detail=str(e))

        # Check if user already exists in canonical 'users' collection
        existing = await db['users'].find_one({'$or': [{'email': email}, {'googleId': google_id}]})

        if existing:
            user_id = str(existing['_id'])
            update_data: Dict[str, Any] = {
                'googleId': google_id,
                'email_verified': True,
                'email_verified_at': existing.get('email_verified_at') or existing.get('emailVerifiedAt') or now,
                'updated_at': now
            }
            if picture_url and not existing.get('profileImageUrl'):
                update_data['profileImageUrl'] = picture_url
            providers = existing.get('authProviders', [])
            if 'google' not in providers:
                providers.append('google')
                update_data['authProviders'] = providers

            # If existing user does not yet have a phone, persist supplied phone as unverified
            if norm_phone and not existing.get('phone_number'):
                # Check for collision with another user
                conflict = await db['users'].find_one({'phone_number': norm_phone, '_id': {'$ne': existing['_id']}})
                if conflict:
                    raise HTTPException(status_code=400, detail='Mobile phone number is already registered to another account.')
                update_data['phone_number'] = norm_phone
                update_data['phone_verified'] = False

            await db['users'].update_one({'_id': ObjectId(user_id)}, {'$set': update_data})
            user_doc = await db['users'].find_one({'_id': ObjectId(user_id)})
            user = User.from_mongo(user_doc)
            user.id = user_id
            logger.info(f"Existing user {user_id} logged in with Google (email={email}).")
        else:
            # Check if user existed in legacy pending_users
            pending_existing = await db['pending_users'].find_one({'$or': [{'email': email}, {'googleId': google_id}]})
            if pending_existing:
                user_id = str(pending_existing['_id'])
                pending_existing['googleId'] = google_id
                pending_existing['email_verified'] = True
                pending_existing['email_verified_at'] = now
                providers = pending_existing.get('authProviders', [])
                if 'google' not in providers:
                    providers.append('google')
                    pending_existing['authProviders'] = providers
                if norm_phone and not pending_existing.get('phone_number'):
                    pending_existing['phone_number'] = norm_phone
                    pending_existing['phone_verified'] = False

                # Migrate from pending_users into canonical users collection
                pending_existing['updated_at'] = now
                await db['users'].update_one({'_id': ObjectId(user_id)}, {'$set': pending_existing}, upsert=True)
                try:
                    await db['pending_users'].delete_one({'_id': ObjectId(user_id)})
                except Exception:
                    pass
                user = User.from_mongo(pending_existing)
                user.id = user_id
                logger.info(f"Pending user {user_id} migrated to canonical users via Google auth.")
            else:
                # Separate Login vs Registration behavior:
                # Login must not silently create an account for an unregistered Google user.
                if mode == "login":
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="No account found with this Google email. Please register first."
                    )

                # Brand new user -> register directly into canonical 'users' collection
                if norm_phone:
                    conflict = await db['users'].find_one({'phone_number': norm_phone})
                    if conflict:
                        raise HTTPException(status_code=400, detail='Mobile phone number is already registered to another account.')

                random_pwd = get_password_hash(secrets.token_urlsafe(32))
                user = User(
                    name=full_name,
                    firstName=first_name,
                    lastName=last_name,
                    email=email,
                    phone_number=norm_phone,
                    phone_verified=False,  # Unverified until verified via OTP
                    hashed_password=random_pwd,
                    accountType=account_type or 'business',
                    authProviders=['google'],
                    googleId=google_id,
                    email_verified=True,
                    email_verified_at=now,
                    termsAcceptedAt=now,
                    profileImageUrl=picture_url,
                    role=None,  # Requires role selection on first login
                    onboardingCompleted=False,
                    onboarding_step=1,
                    created_at=now,
                    updated_at=now
                )
                doc = user.model_dump(by_alias=True, exclude={'id'})

                result = await db['users'].insert_one(doc)
                user.id = str(result.inserted_id)

                # Provision default Free subscription
                try:
                    from app.services.credit_service import CreditService
                    await CreditService.get_or_create_subscription(db, user.id)
                except Exception as e:
                    logger.warning(f"Could not provision subscription for Google user {user.id}: {e}")

                logger.info(f"New user registered directly into users via Google: id={user.id}, email={email}, phone={norm_phone}")

        # Issue access & refresh tokens via canonical session creator
        jwt_access_token, jwt_refresh_token = await AuthService.create_session(db, user.id)
        return user, jwt_access_token, jwt_refresh_token
