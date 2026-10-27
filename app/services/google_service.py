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
            or "260412504334-00s4ah5tslv9rgso3g86fcb079bb84nr.apps.googleusercontent.com"
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
        mode: str = 'login',
        phone_number: Optional[str] = None,
        country_code: Optional[str] = None,
        phone_verification_token: Optional[str] = None
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

        # Normalize phone number if supplied directly
        norm_phone = None
        if phone_number and str(phone_number).strip():
            from app.utils.phone import normalize_phone_number, InvalidPhoneNumberException
            try:
                norm_phone = normalize_phone_number(str(phone_number).strip(), country_code=country_code)
            except InvalidPhoneNumberException as e:
                raise HTTPException(status_code=400, detail=str(e))

        m = (mode or "login").lower().strip()

        # Check if an existing account matches email or Google ID
        existing = await db['users'].find_one({'$or': [{'email': email}, {'googleId': google_id}]})
        if not existing:
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
                if picture_url and not pending_existing.get('profileImageUrl'):
                    pending_existing['profileImageUrl'] = picture_url
                pending_existing['updated_at'] = now
                await db['users'].update_one({'_id': ObjectId(user_id)}, {'$set': pending_existing}, upsert=True)
                try:
                    await db['pending_users'].delete_one({'_id': ObjectId(user_id)})
                except Exception:
                    pass
                existing = await db['users'].find_one({'_id': ObjectId(user_id)})

        if m == "login":
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No account found with this Google email. Please register first. Please sign up first."
                )
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

            if norm_phone and not existing.get('phone_number'):
                update_data['phone_number'] = norm_phone

            await db['users'].update_one({'_id': ObjectId(user_id)}, {'$set': update_data})
            user_doc = await db['users'].find_one({'_id': ObjectId(user_id)})
            user = User.from_mongo(user_doc)
            user.id = user_id
            logger.info(f"Existing user {user_id} logged in with Google (email={email}).")

        else:
            # mode == "signup"
            # 1. Reject if email or Google ID already exists
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists. Please log in."
                )

            # 2. If phone verification token is passed, validate it and check if phone already registered
            verified_phone = norm_phone
            phone_is_verified = False

            if phone_verification_token:
                pv = await db["phone_verifications"].find_one({
                    "verification_token": phone_verification_token,
                    "expires_at": {"$gt": now}
                })
                if pv and pv.get("phone_number"):
                    verified_phone = pv["phone_number"]
                    phone_is_verified = True
                    # Check if phone already registered to another account
                    conflict_phone = await db['users'].find_one({"phone_number": verified_phone})
                    if conflict_phone:
                        if str(conflict_phone.get("_id")) == str(pv.get("user_id")) or not conflict_phone.get("email"):
                            user_id = str(conflict_phone["_id"])
                            await db['users'].update_one(
                                {"_id": conflict_phone["_id"]},
                                {"$set": {
                                    "email": email,
                                    "googleId": google_id,
                                    "email_verified": True,
                                    "phone_verified": True,
                                    "name": full_name or conflict_phone.get("name"),
                                    "firstName": first_name or conflict_phone.get("firstName"),
                                    "lastName": last_name or conflict_phone.get("lastName"),
                                    "profileImageUrl": picture_url or conflict_phone.get("profileImageUrl"),
                                    "updated_at": now
                                }, "$addToSet": {"authProviders": "google"}}
                            )
                            user_doc = await db['users'].find_one({"_id": ObjectId(user_id)})
                            user = User.from_mongo(user_doc)
                            user.phone_verified = True
                            user.id = user_id
                            jwt_access_token, jwt_refresh_token = await AuthService.create_session(db, user.id)
                            return user, jwt_access_token, jwt_refresh_token
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="An account with this mobile number is already registered. Please log in."
                            )
                    await db["phone_verifications"].update_one(
                        {"_id": pv["_id"]},
                        {"$set": {"used": True, "used_at": now}}
                    )
            elif norm_phone:
                conflict_phone = await db['users'].find_one({"phone_number": norm_phone})
                if conflict_phone:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="An account with this mobile number is already registered. Please log in."
                    )

            # 3. Create new user via Google
            random_pwd = get_password_hash(secrets.token_urlsafe(32))
            auth_provs = ['google']
            if phone_is_verified:
                auth_provs.append('phone')

            user = User(
                name=full_name,
                firstName=first_name,
                lastName=last_name,
                email=email,
                phone_number=verified_phone,
                phone_verified=phone_is_verified,
                hashed_password=random_pwd,
                accountType=account_type or 'business',
                authProviders=auth_provs,
                googleId=google_id,
                email_verified=True,
                email_verified_at=now,
                termsAcceptedAt=now,
                profileImageUrl=picture_url,
                role=None,
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

            logger.info(f"New user registered directly into users via Google: id={user.id}, email={email}")

        # Issue access & refresh tokens via canonical session creator
        jwt_access_token, jwt_refresh_token = await AuthService.create_session(db, user.id)
        return user, jwt_access_token, jwt_refresh_token

