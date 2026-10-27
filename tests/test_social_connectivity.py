import uuid
import random
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token

pytestmark = pytest.mark.asyncio

_phone_counter = 0


import httpx
from app.services.instagram_service import InstagramService
from app.services.linkedin_service import LinkedInService

@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield

@pytest.fixture(autouse=True)
def mock_social_oauth_providers():
    """Mock external social OAuth provider APIs (Meta & LinkedIn) during tests."""
    with patch.object(InstagramService, "exchange_code_for_token", new_callable=AsyncMock) as mock_ig_token, \
         patch.object(InstagramService, "get_instagram_profile", new_callable=AsyncMock) as mock_ig_profile, \
         patch.object(LinkedInService, "exchange_code_for_token", new_callable=AsyncMock) as mock_li_token, \
         patch.object(LinkedInService, "get_linkedin_profile", new_callable=AsyncMock) as mock_li_profile:

        mock_ig_token.return_value = {"access_token": "mock_ig_access_token", "user_id": "1784140001"}
        mock_ig_profile.return_value = {
            "id": "1784140001",
            "username": "apex_biz",
            "account_type": "BUSINESS",
            "profile_picture_url": ""
        }

        mock_li_token.return_value = {
            "access_token": "mock_li_access_token",
            "expires_in": 5184000,
            "scope": "openid profile email w_member_social"
        }
        mock_li_profile.return_value = {
            "sub": "888999111",
            "name": "Apex LinkedIn Official",
            "email": "apex@example.com"
        }

        original_get = httpx.AsyncClient.get

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            if "graph.facebook.com" in url_str:
                resp = MagicMock()
                resp.status_code = 200
                if "oauth/access_token" in url_str:
                    resp.json.return_value = {"access_token": "mock_fb_access_token"}
                    resp.text = '{"access_token": "mock_fb_access_token"}'
                elif "me/accounts" in url_str:
                    resp.json.return_value = {
                        "data": [{
                            "id": "109876543210987",
                            "name": "Apex Official FB Page",
                            "access_token": "mock_fb_page_token"
                        }]
                    }
                else:
                    resp.json.return_value = {"id": "109876543210987", "name": "Apex Official FB Page"}
                return resp
            return await original_get(self, url, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "get", mock_get):
            yield


async def create_user_with_token(db, role: str = "businessman", name: str = "Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    phone_suffix = f"{random.randint(10000000, 99999999)}{_phone_counter % 10}"
    phone = f"+919{phone_suffix}"

    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": phone,
        "hashed_password": get_password_hash("Password@123"),
        "role": role,
        "phone_verified": True,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["users"].insert_one(user_doc)
    token = create_access_token(subject=str(user_id))
    return str(user_id), token, user_doc


async def mark_brand_kit_completed(db, user_id: str, business_name: str = "Apex Corp"):
    """Helper to provision a completed Brand Kit and business for a user."""
    now = datetime.now(timezone.utc)
    business_id = ObjectId()

    await db["businesses"].update_one(
        {"owner_id": user_id},
        {"$set": {
            "_id": business_id,
            "owner_id": user_id,
            "name": business_name,
            "category": "Tech",
            "location": "Mumbai",
            "brand_kit_status": "completed",
            "brand_kit_completed": True,
            "brand_kit_completed_at": now,
            "social_connectivity_completed": False,
            "social_connectivity_completed_at": None,
            "connected_platforms": [],
            "updated_at": now,
        }},
        upsert=True
    )

    await db["brand_kits"].update_one(
        {"owner_id": user_id},
        {"$set": {
            "business_id": business_id,
            "owner_id": user_id,
            "business_name": business_name,
            "logo_url": "/uploads/brand/test_logo.png",
            "primary_color": "#7C3AED",
            "secondary_color": "#F97316",
            "accent_color": "#10B981",
            "font": "Inter",
            "brand_kit_status": "completed",
            "brand_kit_completed": True,
            "brand_kit_completed_at": now,
            "updated_at": now,
        }},
        upsert=True
    )


# --------------------------------------------------------------------------
# 1. No Connected Accounts (Brand Kit completed -> should_show_modal = True)
# --------------------------------------------------------------------------
async def test_no_connected_accounts_shows_modal():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="No Social User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "businessman"
        assert data["brand_kit_completed"] is True
        assert data["social_connectivity_completed"] is False
        assert data["should_show_modal"] is True
        assert data["connected_count"] == 0
        assert data["platforms"]["instagram"]["connected"] is False
        assert data["platforms"]["facebook"]["connected"] is False
        assert data["platforms"]["linkedin"]["connected"] is False

        # Alias /api/social/onboarding-status
        alias_res = await ac.get("/api/social/onboarding-status", headers=headers)
        assert alias_res.status_code == 200
        assert alias_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 2. Brand Kit Prerequisite (Brand Kit incomplete -> should_show_modal = False)
# --------------------------------------------------------------------------
async def test_brand_kit_incomplete_prerequisite():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Incomplete Brand User")
    # Brand Kit is NOT completed (either no record or draft)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["brand_kit_completed"] is False
        assert data["social_connectivity_completed"] is False
        # Brand Kit modal must show first, so social modal must NOT show yet
        assert data["should_show_modal"] is False


# --------------------------------------------------------------------------
# 3. OAuth Initiation For All 3 Platforms (Instagram, Facebook, LinkedIn)
# --------------------------------------------------------------------------
async def test_oauth_initiation_all_platforms():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="OAuth Init User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Instagram connect
        res_ig = await ac.get("/api/instagram/connect", headers=headers)
        assert res_ig.status_code == 200
        ig_auth_url = res_ig.json()["authorization_url"]
        assert "state=" in ig_auth_url
        assert ig_auth_url.startswith("https://www.instagram.com/oauth/authorize")
        assert "facebook.com" not in ig_auth_url
        assert "enable_fb_login=0" in ig_auth_url
        ig_state_doc = await db["instagram_oauth_states"].find_one({"user_id": user_id})
        assert ig_state_doc is not None

        # 2. Facebook connect
        res_fb = await ac.get("/api/facebook/connect", headers=headers)
        assert res_fb.status_code == 200
        fb_auth_url = res_fb.json()["authorization_url"]
        assert "state=" in fb_auth_url
        assert "facebook.com" in fb_auth_url
        fb_state_doc = await db["facebook_oauth_states"].find_one({"user_id": user_id})
        assert fb_state_doc is not None

        # 3. LinkedIn connect
        res_li = await ac.get("/api/linkedin/connect", headers=headers)
        assert res_li.status_code == 200
        li_auth_url = res_li.json()["authorization_url"]
        assert "state=" in li_auth_url
        li_state_doc = await db["linkedin_oauth_states"].find_one({"user_id": user_id})
        assert li_state_doc is not None


# --------------------------------------------------------------------------
# 4. Successful Verified Connection (Instagram, Facebook, LinkedIn)
# --------------------------------------------------------------------------
async def test_successful_connections_and_completion():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Connect Success User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Step 4a: Initiate and complete Instagram connection
        ig_init = await ac.get("/api/instagram/connect", headers=headers)
        ig_state = ig_init.json()["authorization_url"].split("state=")[1]

        ig_cb = await ac.get(f"/api/instagram/callback?code=test_ig_code&state={ig_state}", follow_redirects=False)
        assert ig_cb.status_code in [302, 307]
        assert "instagram_connected=true" in ig_cb.headers["location"]

        # Now Instagram is connected! Onboarding step 2 must be marked complete!
        status_after_ig = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        data_ig = status_after_ig.json()
        assert data_ig["social_connectivity_completed"] is True
        assert data_ig["should_show_modal"] is False
        assert data_ig["connected_count"] == 1
        assert data_ig["platforms"]["instagram"]["connected"] is True

        # Step 4b: Connect Facebook
        fb_init = await ac.get("/api/facebook/connect", headers=headers)
        fb_state = fb_init.json()["authorization_url"].split("state=")[1]

        fb_cb = await ac.get(f"/api/facebook/callback?code=test_fb_code&state={fb_state}", follow_redirects=False)
        assert fb_cb.status_code in [302, 307]
        assert "facebook_connected=true" in fb_cb.headers["location"]
        # Ensure token is NOT leaked in redirect query
        assert "fb_access_token" not in fb_cb.headers["location"]

        # Step 4c: Connect LinkedIn
        li_init = await ac.get("/api/linkedin/connect", headers=headers)
        li_state = li_init.json()["authorization_url"].split("state=")[1]

        li_cb = await ac.get(f"/api/linkedin/callback?code=test_li_code&state={li_state}", follow_redirects=False)
        assert li_cb.status_code in [302, 307]
        assert "linkedin_connected=true" in li_cb.headers["location"]

        # Check total status: all 3 platforms connected, onboarding complete
        final_status = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        final_data = final_status.json()
        assert final_data["connected_count"] == 3
        assert final_data["social_connectivity_completed"] is True
        assert final_data["should_show_modal"] is False
        assert final_data["platforms"]["instagram"]["connected"] is True
        assert final_data["platforms"]["facebook"]["connected"] is True
        assert final_data["platforms"]["linkedin"]["connected"] is True


# --------------------------------------------------------------------------
# 5. Failed or Cancelled Authorization
# --------------------------------------------------------------------------
async def test_cancelled_or_failed_authorization():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Cancel User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # User cancels authorization on LinkedIn
        li_cb = await ac.get(
            "/api/linkedin/callback?error=user_cancelled_authorize&error_description=User+cancelled",
            follow_redirects=False
        )
        assert li_cb.status_code in [302, 307]
        assert "linkedin_error=" in li_cb.headers["location"]

        # Connection must not be marked complete
        status_res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert status_res.json()["social_connectivity_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 6. Invalid OAuth State (CSRF prevention)
# --------------------------------------------------------------------------
async def test_invalid_oauth_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Invalid state
        fake_state = "invalid_random_state_12345"
        res = await ac.get(f"/api/linkedin/callback?code=test_code&state={fake_state}", follow_redirects=False)
        assert res.status_code in [302, 307]
        assert "Invalid+state+token" in res.headers["location"]

        # Missing state
        res_missing = await ac.get("/api/facebook/callback?code=test_code", follow_redirects=False)
        assert res_missing.status_code in [302, 307]
        assert "error=" in res_missing.headers["location"]


# --------------------------------------------------------------------------
# 7. Token Security & Encryption (Tokens NEVER returned to client)
# --------------------------------------------------------------------------
async def test_token_encryption_and_client_masking():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Token Sec User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Connect LinkedIn
        li_init = await ac.get("/api/linkedin/connect", headers=headers)
        state = li_init.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/linkedin/callback?code=test_code&state={state}", follow_redirects=False)

        # Inspect DB document: encrypted_access_token must NOT equal plaintext "DEMO_LI_TOKEN"
        conn_doc = await db["linkedin_connections"].find_one({"user_id": user_id, "platform": "linkedin"})
        assert conn_doc is not None
        assert conn_doc["encrypted_access_token"] != "DEMO_LI_TOKEN"

        # Endpoints must NEVER return access tokens or secrets
        status_res = await ac.get("/api/linkedin/status", headers=headers)
        assert "access_token" not in status_res.json()
        assert "encrypted_access_token" not in status_res.json()

        onboarding_res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert "access_token" not in onboarding_res.text
        assert "encrypted_access_token" not in onboarding_res.text


# --------------------------------------------------------------------------
# 8. Duplicate Connection Attempts Are Idempotent
# --------------------------------------------------------------------------
async def test_duplicate_connections_idempotent():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Idempotent Social User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Connect LinkedIn 1st time
        init1 = await ac.get("/api/linkedin/connect", headers=headers)
        state1 = init1.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/linkedin/callback?code=test1&state={state1}", follow_redirects=False)

        # Connect LinkedIn 2nd time (reconnection)
        init2 = await ac.get("/api/linkedin/connect", headers=headers)
        state2 = init2.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/linkedin/callback?code=test2&state={state2}", follow_redirects=False)

        # Assert only 1 connection document exists in linkedin_connections collection
        count = await db["linkedin_connections"].count_documents({"user_id": user_id, "platform": "linkedin"})
        assert count == 1


# --------------------------------------------------------------------------
# 9. Cross-User Data Isolation
# --------------------------------------------------------------------------
async def test_cross_user_social_isolation():
    db = get_database()
    user_a, token_a, _ = await create_user_with_token(db, role="businessman", name="User A")
    user_b, token_b, _ = await create_user_with_token(db, role="businessman", name="User B")
    await mark_brand_kit_completed(db, user_a)
    await mark_brand_kit_completed(db, user_b)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A connects Instagram
        init_a = await ac.get("/api/instagram/connect", headers=headers_a)
        state_a = init_a.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/instagram/callback?code=code_a&state={state_a}", follow_redirects=False)

        # User A status: connected_count = 1
        res_a = await ac.get("/api/v1/social/onboarding-status", headers=headers_a)
        assert res_a.json()["connected_count"] == 1
        assert res_a.json()["platforms"]["instagram"]["connected"] is True

        # User B status: connected_count = 0 (completely isolated!)
        res_b = await ac.get("/api/v1/social/onboarding-status", headers=headers_b)
        assert res_b.json()["connected_count"] == 0
        assert res_b.json()["platforms"]["instagram"]["connected"] is False
        assert res_b.json()["should_show_modal"] is True

        # User B cannot disconnect User A's account
        await ac.post("/api/v1/social/disconnect/instagram", headers=headers_b)
        # User A must still be connected
        res_a_after = await ac.get("/api/v1/social/onboarding-status", headers=headers_a)
        assert res_a_after.json()["connected_count"] == 1


# --------------------------------------------------------------------------
# 10. Disconnecting Accounts & Reopening Eligibility
# --------------------------------------------------------------------------
async def test_disconnect_last_account_reopens_modal():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Disconnect User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Connect Instagram and Facebook
        ig_init = await ac.get("/api/instagram/connect", headers=headers)
        ig_state = ig_init.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/instagram/callback?code=ig&state={ig_state}", follow_redirects=False)

        fb_init = await ac.get("/api/facebook/connect", headers=headers)
        fb_state = fb_init.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/facebook/callback?code=fb&state={fb_state}", follow_redirects=False)

        status_2 = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert status_2.json()["connected_count"] == 2
        assert status_2.json()["social_connectivity_completed"] is True
        assert status_2.json()["should_show_modal"] is False

        # 1. Disconnect Facebook (1 account remains)
        dis_fb = await ac.post("/api/v1/social/disconnect/facebook", headers=headers)
        assert dis_fb.status_code == 200
        assert dis_fb.json()["social_connectivity_completed"] is True
        assert dis_fb.json()["should_show_modal"] is False

        status_1 = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert status_1.json()["connected_count"] == 1
        assert status_1.json()["social_connectivity_completed"] is True
        assert status_1.json()["should_show_modal"] is False

        # 2. Disconnect Instagram (the LAST connected account!)
        dis_ig = await ac.post("/api/v1/social/disconnect/instagram", headers=headers)
        assert dis_ig.status_code == 200
        # When 0 accounts remain: social_connectivity_completed becomes False!
        assert dis_ig.json()["social_connectivity_completed"] is False
        assert dis_ig.json()["should_show_modal"] is True

        # Next dashboard visit: modal becomes eligible to reopen!
        status_0 = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert status_0.json()["connected_count"] == 0
        assert status_0.json()["social_connectivity_completed"] is False
        assert status_0.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 11. Persistence Across Sessions / Relogin
# --------------------------------------------------------------------------
async def test_persistence_across_sessions():
    db = get_database()
    user_id, token1, _ = await create_user_with_token(db, role="businessman", name="Session User")
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers1 = {"Authorization": f"Bearer {token1}"}

        # Connect Facebook in session 1
        fb_init = await ac.get("/api/facebook/connect", headers=headers1)
        fb_state = fb_init.json()["authorization_url"].split("state=")[1]
        await ac.get(f"/api/facebook/callback?code=fb&state={fb_state}", follow_redirects=False)

        # Simulate relogin (new token)
        token2 = create_access_token(subject=user_id)
        headers2 = {"Authorization": f"Bearer {token2}"}

        res = await ac.get("/api/v1/social/onboarding-status", headers=headers2)
        assert res.status_code == 200
        assert res.json()["social_connectivity_completed"] is True
        assert res.json()["should_show_modal"] is False
        assert res.json()["platforms"]["facebook"]["connected"] is True


# --------------------------------------------------------------------------
# 12. Influencer Role Exclusion
# --------------------------------------------------------------------------
async def test_influencer_role_exclusion():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="influencer", name="Influencer Star")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "influencer"
        # Influencer does NOT see the Businessman popup
        assert data["should_show_modal"] is False
        assert data["social_connectivity_completed"] is True


# --------------------------------------------------------------------------
# 13. Create Account URLs Support
# --------------------------------------------------------------------------
async def test_create_account_urls():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Main endpoint
        res = await ac.get("/api/v1/social/create-account-urls")
        assert res.status_code == 200
        data = res.json()
        assert "instagram.com" in data["instagram"]
        assert "facebook.com" in data["facebook"]
        assert "linkedin.com" in data["linkedin"]
        assert "urls" in data
        assert "instructions" in data

        # 2. Aliases on /api/v1/social
        res_alias1 = await ac.get("/api/v1/social/create-account")
        assert res_alias1.status_code == 200
        res_alias2 = await ac.get("/api/v1/social/signup-urls")
        assert res_alias2.status_code == 200

        # 3. Aliases on /api/social
        res_alias3 = await ac.get("/api/social/create-account-urls")
        assert res_alias3.status_code == 200
        res_alias4 = await ac.get("/api/social/signup-urls")
        assert res_alias4.status_code == 200

        # 4. Individual platform endpoints
        ig_res = await ac.get("/api/instagram/signup-url")
        assert ig_res.status_code == 200
        assert "instagram.com" in ig_res.json()["url"]

        fb_res = await ac.get("/api/facebook/signup-url")
        assert fb_res.status_code == 200
        assert "facebook.com" in fb_res.json()["url"]

        li_res = await ac.get("/api/linkedin/signup-url")
        assert li_res.status_code == 200
        assert "linkedin.com" in li_res.json()["url"]

