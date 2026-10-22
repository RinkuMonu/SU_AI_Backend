import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from bson import ObjectId
from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import get_password_hash, create_access_token
from app.services.sms_service import SMSService

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
def mock_sms_service():
    """Mock SMS delivery for unit testing — no real SMS calls in test suite."""
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"type": "success", "request_id": "mock_req_12345"}
        yield mock_send

@pytest.fixture(autouse=True)
async def setup_and_cleanup_db():
    connect_to_mongo()
    db = get_database()
    
    # Ensure admin user exists for tests
    admin_user = await db["users"].find_one({"email": "admin@example.com"})
    if not admin_user:
        admin_data = {
            "name": "Admin",
            "email": "admin@example.com",
            "hashed_password": get_password_hash("Admin@123"),
            "role": "admin",
            "email_verified": True
        }
        await db["users"].insert_one(admin_data)
        
    yield
    if db is not None:
        await db["users"].delete_many({"email": {"$regex": r".*@example\.com|.*@test\.com"}})
        await db["otps"].delete_many({"email": {"$regex": r".*@example\.com|.*@test\.com"}})
        await db["businesses"].delete_many({"userId": {"$exists": True}})
        await db["refresh_sessions"].delete_many({})

@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

# =====================================================================
# HEAD Tests (Email & Password / Full Name / Individual Fields)
# =====================================================================
@pytest.mark.asyncio
async def test_signup_with_individual_fields(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "firstName": "Sejal",
        "lastName": "Gupta",
        "contactNumber": "+91 98765 43210",
        "email": "sejal_signup_test@example.com",
        "password": "Password123!",
        "otp": "123456",
        "accountType": "business",
        "termsAccepted": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    user = data["data"]["user"]
    assert user["firstName"] == "Sejal"
    assert user["lastName"] == "Gupta"
    assert user["fullName"] == "Sejal Gupta"
    assert user["contactNumber"] == "+91 98765 43210"
    assert user["email"] == "sejal_signup_test@example.com"
    assert user["emailVerified"] is True

@pytest.mark.asyncio
async def test_signup_with_full_name_backwards_compatible(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    assert res.status_code == 200
    assert res.json()["success"] is True

@pytest.mark.asyncio
async def test_duplicate_signup(async_client):
    from app.core.database import get_database
    db = get_database()
    await db["users"].delete_many({"email": "dup@example.com"})
    await db["pending_users"].delete_many({"email": "dup@example.com"})
    await db["users"].insert_one({
        "email": "dup@example.com",
        "firstName": "Existing",
        "lastName": "User",
        "hashed_password": "hashed_pw",
        "email_verified": True
    })

    req = {
        "firstName": "Test",
        "lastName": "Duplicate",
        "email": "dup@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    }
    res = await async_client.post("/api/v1/auth/signup", json=req)
    assert res.status_code == 409

@pytest.mark.asyncio
async def test_login(async_client):
    await async_client.post("/api/v1/auth/signup", json={
        "firstName": "Login",
        "lastName": "User",
        "contactNumber": "9876543210",
        "email": "login_user@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    res = await async_client.post("/api/v1/auth/login", json={
        "email": "login_user@example.com",
        "password": "Password123"
    })
    assert res.status_code == 200
    assert "accessToken" in res.json()["data"]
    assert "set-cookie" in res.headers

# =====================================================================
# Sejal Tests (MSG91 Phone OTP / Role Selection / Dashboards / Security)
# =====================================================================
async def test_phone_signup_and_sign_in_flow(mock_sms_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        test_phone = "+919876543210"
        test_email = "rohan@example.com"
        
        # 1. Clean previous test data
        db = get_database()
        await db["users"].delete_many({"phone_number": test_phone})
        await db["users"].delete_many({"email": test_email})
        await db["otps"].delete_many({"phone_number": test_phone})

        # 2. User signup via Phone & Email (no verification required on signup)
        response = await ac.post("/api/v1/auth/signup", json={
            "name": "Rohan Sharma",
            "phone_number": "9876543210",  # Will be normalized to +919876543210
            "email": test_email,
            "password": "Password@123",
            "confirmPassword": "Password@123"
        })
        assert response.status_code == 201
        data = response.json()
        assert "detail" in data
        assert data.get("code") == "SIGNUP_SUCCESS"

        # 3. User is directly created in active users collection with phone_verified=False
        active_user = await db["users"].find_one({"phone_number": test_phone})
        assert active_user is not None
        assert active_user["phone_verified"] is False
        assert active_user["email_verified"] is True
        assert active_user["email"] == test_email

        # 4. Sign in: Step 1 - user enters mobile number and password
        # Backend verifies password, sends mobile OTP via SMS, and returns 403 PHONE_NOT_VERIFIED
        login_attempt_1 = await ac.post("/api/v1/auth/login", json={
            "phone_number": "9876543210",
            "password": "Password@123"
        })
        assert login_attempt_1.status_code == 403
        assert login_attempt_1.json().get("code") == "PHONE_NOT_VERIFIED"
        assert mock_sms_service.called, "SMS OTP must be dispatched when unverified user signs in"

        # 5. Inspect OTP document in DB
        otp_doc = await db["otps"].find_one({"phone_number": test_phone})
        assert otp_doc is not None
        assert "otp_hash" in otp_doc
        assert otp_doc.get("otp") is None, "Plaintext OTP must NEVER be stored in DB"

        # 6. Set deterministic OTP hash for testing verification
        test_otp = "456789"
        await db["otps"].update_one(
            {"phone_number": test_phone},
            {"$set": {"otp_hash": get_password_hash(test_otp)}}
        )

        # 7. Sign in: Step 2 - verify mobile OTP
        verify_response = await ac.post("/api/v1/auth/verify-otp", json={
            "phone_number": "9876543210",
            "otp": test_otp
        })
        assert verify_response.status_code == 200
        verify_data = verify_response.json()
        assert "access_token" in verify_data
        assert verify_data["user"]["phone_verified"] is True
        assert verify_data["user"]["phone_number"] == test_phone

        # 8. Single-use OTP: OTP record is deleted after successful verification
        remaining_otp = await db["otps"].find_one({"phone_number": test_phone})
        assert remaining_otp is None, "OTP must be deleted after successful verification"

        # 9. Subsequent login with verified phone number and password succeeds directly
        login_response = await ac.post("/api/v1/auth/login", json={
            "phone_number": "9876543210",
            "password": "Password@123"
        })
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        assert login_response.json()["user"]["phone_verified"] is True

        # 10. /auth/me returns user profile
        me_res = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["phone_number"] == test_phone
        assert me_res.json()["phone_verified"] is True

async def test_invalid_phone_numbers():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        invalid_numbers = ["12345", "0000000000", "5876543210", "abc-phone", ""]
        for num in invalid_numbers:
            response = await ac.post("/api/v1/auth/signup", json={
                "name": "Invalid Phone",
                "phone_number": num,
                "email": "valid@example.com",
                "password": "Password@123",
                "confirmPassword": "Password@123"
            })
            assert response.status_code in [400, 422], f"Expected 400/422 for invalid phone '{num}'"

async def test_missing_email_on_signup():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/signup", json={
            "name": "Missing Email",
            "phone_number": "9876543210",
            "password": "Password@123",
            "confirmPassword": "Password@123"
        })
        assert response.status_code in [400, 422], "Email is mandatory on signup"

async def test_duplicate_phone_number():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        dup_phone = "+919111222333"
        await db["users"].delete_many({"phone_number": dup_phone})
        await db["users"].insert_one({
            "name": "Existing User",
            "phone_number": dup_phone,
            "email": "existing@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Pass@123"),
            "role": "user"
        })

        response = await ac.post("/api/v1/auth/signup", json={
            "name": "New User Same Phone",
            "phone_number": "9111222333",
            "email": "different@example.com",
            "password": "Password@123",
            "confirmPassword": "Password@123"
        })
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

async def test_otp_failure_attempts_and_cooldown(mock_sms_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        test_phone = "+919777888999"
        db = get_database()
        await db["users"].delete_many({"phone_number": test_phone})
        await db["otps"].delete_many({"phone_number": test_phone})

        # Signup
        await ac.post("/api/v1/auth/signup", json={
            "name": "Cooldown Test",
            "phone_number": test_phone,
            "email": "cooldown@example.com",
            "password": "Password@123",
            "confirmPassword": "Password@123"
        })

        # Sign in attempt triggers OTP
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": test_phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 403

        # Wrong OTP -> 400
        res = await ac.post("/api/v1/auth/verify-otp", json={
            "phone_number": test_phone,
            "otp": "000000"
        })
        assert res.status_code == 400
        assert "Invalid OTP" in res.json()["detail"]

        # Resend cooldown -> 429
        resend_res = await ac.post("/api/v1/auth/resend-otp", json={
            "phone_number": test_phone
        })
        assert resend_res.status_code == 429
        assert "wait" in resend_res.json()["detail"].lower()

async def test_otp_max_attempts_lockout(mock_sms_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        test_phone = "+919555666777"
        db = get_database()
        await db["users"].delete_many({"phone_number": test_phone})
        await db["otps"].delete_many({"phone_number": test_phone})

        # Signup and login to create OTP
        await ac.post("/api/v1/auth/signup", json={
            "name": "Lockout Test",
            "phone_number": test_phone,
            "email": "lockout@example.com",
            "password": "Password@123"
        })
        await ac.post("/api/v1/auth/login", json={
            "phone_number": test_phone,
            "password": "Password@123"
        })

        # Simulate 5 failed attempts
        await db["otps"].update_one(
            {"phone_number": test_phone},
            {"$set": {"attempts": 5}}
        )

        # 6th attempt should trigger lockout and delete OTP
        lock_res = await ac.post("/api/v1/auth/verify-otp", json={
            "phone_number": test_phone,
            "otp": "123456"
        })
        assert lock_res.status_code == 400
        assert "Too many failed attempts" in lock_res.json()["detail"]

        # Confirm OTP was deleted
        assert await db["otps"].find_one({"phone_number": test_phone}) is None

async def test_otp_expiration(mock_sms_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        test_phone = "+919444333222"
        db = get_database()
        await db["users"].delete_many({"phone_number": test_phone})
        await db["otps"].delete_many({"phone_number": test_phone})

        await ac.post("/api/v1/auth/signup", json={
            "name": "Expired Test",
            "phone_number": test_phone,
            "email": "expired@example.com",
            "password": "Password@123"
        })
        await ac.post("/api/v1/auth/login", json={
            "phone_number": test_phone,
            "password": "Password@123"
        })

        # Set expiration to past
        past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db["otps"].update_one(
            {"phone_number": test_phone},
            {"$set": {"expires_at": past_time}}
        )

        exp_res = await ac.post("/api/v1/auth/verify-otp", json={
            "phone_number": test_phone,
            "otp": "123456"
        })
        assert exp_res.status_code == 400
        assert "expired" in exp_res.json()["detail"].lower()

async def test_sms_provider_failure_on_login(mock_sms_service):
    from fastapi import HTTPException
    mock_sms_service.side_effect = HTTPException(status_code=502, detail="SMS Gateway Error")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        test_phone = "+919333222111"
        db = get_database()
        await db["users"].delete_many({"phone_number": test_phone})

        # Signup succeeds without SMS call
        signup_res = await ac.post("/api/v1/auth/signup", json={
            "name": "SMS Fail",
            "phone_number": test_phone,
            "email": "smsfail@example.com",
            "password": "Password@123"
        })
        assert signup_res.status_code == 201

        # Sign in triggers SMS which fails
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": test_phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 502

async def test_admin_and_legacy_account_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Admin login
        login_res = await ac.post("/api/v1/auth/login", json={
            "email": "admin@example.com",
            "password": "Admin@123"
        })
        assert login_res.status_code == 200
        assert login_res.json()["user"]["role"] == "admin"

        # Legacy email user login
        db = get_database()
        legacy_email = "legacy_verified@example.com"
        await db["users"].delete_many({"email": legacy_email})
        await db["users"].insert_one({
            "name": "Legacy Verified",
            "email": legacy_email,
            "phone_number": None,
            "hashed_password": get_password_hash("Password@123"),
            "role": "user",
            "email_verified": True
        })

        legacy_res = await ac.post("/api/v1/auth/login", json={
            "email": legacy_email,
            "password": "Password@123"
        })
        assert legacy_res.status_code == 200
        assert legacy_res.json()["user"]["email"] == legacy_email

async def test_unverified_phone_login_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        unverified_phone = "+919222111000"
        await db["users"].delete_many({"phone_number": unverified_phone})
        await db["users"].insert_one({
            "name": "Unverified Phone User",
            "phone_number": unverified_phone,
            "email": "unverified@example.com",
            "phone_verified": False,
            "hashed_password": get_password_hash("Password@123"),
            "role": "user"
        })

        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": unverified_phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 403
        assert login_res.json().get("code") == "PHONE_NOT_VERIFIED"


# =====================================================================
# ROLE SELECTION & DASHBOARD REDIRECTION TESTS (REQUIREMENTS 1 - 16)
# =====================================================================

async def test_req_01_and_02_new_registration_and_phone_otp_and_auth(mock_sms_service):
    """
    Req 1 & 2: New registration with phone OTP verification & successful authentication after registration.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        phone = "+919811100001"
        email = "req1_2@example.com"
        db = get_database()
        await db["users"].delete_many({"phone_number": phone})
        await db["users"].delete_many({"email": email})
        await db["otps"].delete_many({"phone_number": phone})

        # Step 1: Signup
        signup_res = await ac.post("/api/v1/auth/signup", json={
            "name": "New User 1",
            "phone_number": phone,
            "email": email,
            "password": "Password@123"
        })
        assert signup_res.status_code == 201

        # Step 2: Unverified login triggers OTP
        login_1 = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_1.status_code == 403
        assert login_1.json().get("code") == "PHONE_NOT_VERIFIED"
        assert mock_sms_service.called

        # Step 3: Inject known OTP hash and verify
        test_otp = "123987"
        await db["otps"].update_one(
            {"phone_number": phone},
            {"$set": {"otp_hash": get_password_hash(test_otp)}}
        )
        verify_res = await ac.post("/api/v1/auth/verify-otp", json={
            "phone_number": phone,
            "otp": test_otp
        })
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert "access_token" in verify_data
        assert verify_data["user"]["phone_verified"] is True
        token = verify_data["access_token"]

        # Step 4: Subsequent login succeeds directly
        login_2 = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_2.status_code == 200
        assert "access_token" in login_2.json()

async def test_req_03_new_user_has_no_selected_role(mock_sms_service):
    """
    Req 3: New user with no selected role.
    Role starts as null, and dashboard access requires role selection.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        phone = "+919811100002"
        email = "req3_norole@example.com"
        db = get_database()
        await db["users"].delete_many({"phone_number": phone})
        await db["otps"].delete_many({"phone_number": phone})

        await ac.post("/api/v1/auth/signup", json={
            "name": "No Role User",
            "phone_number": phone,
            "email": email,
            "password": "Password@123"
        })
        await ac.post("/api/v1/auth/login", json={"phone_number": phone, "password": "Password@123"})
        await db["otps"].update_one({"phone_number": phone}, {"$set": {"otp_hash": get_password_hash("111222")}})
        verify_res = await ac.post("/api/v1/auth/verify-otp", json={"phone_number": phone, "otp": "111222"})
        token = verify_res.json()["access_token"]

        # Check /auth/me -> role is null
        me_res = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["role"] is None

        # Check dashboard route -> 403 Role selection required
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers={"Authorization": f"Bearer {token}"})
        assert dash_res.status_code == 403
        assert "Role selection required" in dash_res.json()["detail"]

async def test_req_04_successful_businessman_role_selection():
    """
    Req 4: Successful Businessman role selection.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100003"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Businessman Candidate",
            "phone_number": phone,
            "email": "businessman_cand@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        token = create_access_token(subject=str(user_res.inserted_id))

        # Select businessman role
        select_res = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert select_res.status_code == 200
        data = select_res.json()
        assert data["role"] == "businessman"
        assert data["success"] is True

        # Check /auth/me
        me_res = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["role"] == "businessman"

        # Check dashboard route
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers={"Authorization": f"Bearer {token}"})
        assert dash_res.status_code == 200
        assert dash_res.json()["dashboard_route"] == "/dashboard/business"

async def test_req_05_successful_influencer_role_selection():
    """
    Req 5: Successful Influencer/Creator role selection.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100004"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Influencer Candidate",
            "phone_number": phone,
            "email": "influencer_cand@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        token = create_access_token(subject=str(user_res.inserted_id))

        # Select influencer role
        select_res = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "influencer"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert select_res.status_code == 200
        data = select_res.json()
        assert data["role"] == "influencer"

        # Check /auth/me
        me_res = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["role"] == "influencer"

        # Check dashboard route
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers={"Authorization": f"Bearer {token}"})
        assert dash_res.status_code == 200
        assert dash_res.json()["dashboard_route"] == "/dashboard/creator"

async def test_req_06_role_persistence_after_fetching_current_user():
    """
    Req 6: Role persistence after fetching the current user from database.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100005"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Persistence User",
            "phone_number": phone,
            "email": "persist@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        user_id = user_res.inserted_id
        token = create_access_token(subject=str(user_id))

        # Update role via API
        await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {token}"}
        )

        # Directly verify database record
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        assert doc["role"] == "businessman"

        # Verify via current user endpoint
        me_res = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["role"] == "businessman"

async def test_req_07_existing_businessman_login_retains_role():
    """
    Req 7: Existing Businessman login retaining its role without re-selection.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100006"
        await db["users"].delete_many({"phone_number": phone})
        await db["users"].insert_one({
            "name": "Existing Businessman",
            "phone_number": phone,
            "email": "existing_bm@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": "businessman"
        })

        # Login directly with phone and password
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["user"]["role"] == "businessman"

        token = login_data["access_token"]
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers={"Authorization": f"Bearer {token}"})
        assert dash_res.status_code == 200
        assert dash_res.json()["dashboard_route"] == "/dashboard/business"

async def test_req_08_existing_influencer_login_retains_role():
    """
    Req 8: Existing Influencer/Creator login retaining its role without re-selection.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100007"
        await db["users"].delete_many({"phone_number": phone})
        await db["users"].insert_one({
            "name": "Existing Creator",
            "phone_number": phone,
            "email": "existing_creator@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": "influencer"
        })

        # Login directly with phone and password
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["user"]["role"] == "influencer"

        token = login_data["access_token"]
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers={"Authorization": f"Bearer {token}"})
        assert dash_res.status_code == 200
        assert dash_res.json()["dashboard_route"] == "/dashboard/creator"

async def test_req_09_existing_user_with_no_role():
    """
    Req 9: Existing user with no role.
    Login exposes role as null, frontend is directed to role selection, and user can choose.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100008"
        await db["users"].delete_many({"phone_number": phone})
        await db["users"].insert_one({
            "name": "No Role Existing",
            "phone_number": phone,
            "email": "norole_exist@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })

        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        assert login_res.json()["user"]["role"] is None

        # User now chooses role
        select_res = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "influencer"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert select_res.status_code == 200
        assert select_res.json()["role"] == "influencer"

async def test_req_10_invalid_role_submission():
    """
    Req 10: Invalid role submission rejected with 400 Bad Request.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100009"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Invalid Role User",
            "phone_number": phone,
            "email": "invalid_role@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        token = create_access_token(subject=str(user_res.inserted_id))

        for bad_role in ["superman", "manager", "moderator", "", " "]:
            res = await ac.post(
                "/api/v1/auth/select-role",
                json={"role": bad_role},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert res.status_code in [400, 422], f"Expected 400 for bad role '{bad_role}'"
            assert "Invalid role" in res.json().get("detail", "")

        # Role in database remains None
        doc = await db["users"].find_one({"_id": ObjectId(user_res.inserted_id)})
        assert doc["role"] is None

async def test_req_11_unauthorized_role_update():
    """
    Req 11: Unauthorized role update.
    1) Normal user cannot escalate to 'admin' (403 Forbidden).
    2) User who already selected a role cannot change to a different role (400 Bad Request).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100010"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Escalation Tester",
            "phone_number": phone,
            "email": "escalation@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        token = create_access_token(subject=str(user_res.inserted_id))

        # 1. Attempt admin escalation
        res_admin = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res_admin.status_code == 403
        assert "Cannot assign administrative role" in res_admin.json()["detail"]

        # 2. Select legitimate role 'businessman'
        res_select = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res_select.status_code == 200

        # 3. Attempt to change already-selected role to 'influencer'
        res_change = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "influencer"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res_change.status_code == 400
        assert "already been set and cannot be modified" in res_change.json()["detail"]

async def test_req_12_attempt_to_change_another_user_role():
    """
    Req 12: Attempt to change another user's role rejected with 403 Forbidden.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone_a = "+919811100011"
        phone_b = "+919811100012"
        await db["users"].delete_many({"phone_number": {"$in": [phone_a, phone_b]}})

        user_a = await db["users"].insert_one({
            "name": "Attacker User A",
            "phone_number": phone_a,
            "email": "user_a@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        user_b = await db["users"].insert_one({
            "name": "Victim User B",
            "phone_number": phone_b,
            "email": "user_b@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })

        token_a = create_access_token(subject=str(user_a.inserted_id))

        # User A tries to change User B's role
        res = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman", "user_id": str(user_b.inserted_id)},
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert res.status_code == 403
        assert "forbidden" in res.json()["detail"].lower()

        # Confirm User B's role is intact
        doc_b = await db["users"].find_one({"_id": ObjectId(user_b.inserted_id)})
        assert doc_b["role"] is None

async def test_req_13_invalid_or_expired_jwt():
    """
    Req 13: Invalid or expired JWT returns 401 Unauthorized.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Invalid signature
        res_invalid = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": "Bearer invalid.fake.token"}
        )
        assert res_invalid.status_code == 401

        # Expired token
        expired_token = create_access_token(
            subject="60a7b45c342d3c148c2e6d5a",
            expires_delta=-timedelta(minutes=30)
        )
        res_expired = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert res_expired.status_code == 401

async def test_req_14_role_specific_api_authorization():
    """
    Req 14: Role-specific API authorization.
    - Businessman can access businessman dashboard, denied influencer dashboard.
    - Influencer can access influencer dashboard, denied businessman dashboard.
    - User with no role denied both.
    - Admin can access both.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        u_bm = await db["users"].insert_one({
            "name": "Auth BM",
            "email": "auth_bm@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": "businessman"
        })
        u_inf = await db["users"].insert_one({
            "name": "Auth INF",
            "email": "auth_inf@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": "influencer"
        })
        u_norole = await db["users"].insert_one({
            "name": "Auth NoRole",
            "email": "auth_norole@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })

        bm_token = create_access_token(subject=str(u_bm.inserted_id))
        inf_token = create_access_token(subject=str(u_inf.inserted_id))
        norole_token = create_access_token(subject=str(u_norole.inserted_id))

        # Admin user
        admin_doc = await db["users"].find_one({"email": "admin@example.com"})
        admin_token = create_access_token(subject=str(admin_doc["_id"]))

        # 1. Businessman accesses Businessman dashboard -> 200
        res = await ac.get("/api/v1/auth/dashboard/businessman", headers={"Authorization": f"Bearer {bm_token}"})
        assert res.status_code == 200

        # 2. Businessman accesses Influencer dashboard -> 403
        res = await ac.get("/api/v1/auth/dashboard/influencer", headers={"Authorization": f"Bearer {bm_token}"})
        assert res.status_code == 403
        assert "Influencer/Creator role required" in res.json()["detail"]

        # 3. Influencer accesses Influencer dashboard -> 200
        res = await ac.get("/api/v1/auth/dashboard/influencer", headers={"Authorization": f"Bearer {inf_token}"})
        assert res.status_code == 200

        # 4. Influencer accesses Businessman dashboard -> 403
        res = await ac.get("/api/v1/auth/dashboard/businessman", headers={"Authorization": f"Bearer {inf_token}"})
        assert res.status_code == 403
        assert "Businessman role required" in res.json()["detail"]

        # 5. User with no role accesses either -> 403 Role selection required
        res = await ac.get("/api/v1/auth/dashboard/businessman", headers={"Authorization": f"Bearer {norole_token}"})
        assert res.status_code == 403
        assert "Role selection required" in res.json()["detail"]

        # 6. Admin accesses both -> 200
        res_bm = await ac.get("/api/v1/auth/dashboard/businessman", headers={"Authorization": f"Bearer {admin_token}"})
        assert res_bm.status_code == 200
        res_inf = await ac.get("/api/v1/auth/dashboard/influencer", headers={"Authorization": f"Bearer {admin_token}"})
        assert res_inf.status_code == 200

async def test_req_15_repeated_role_selection_requests():
    """
    Req 15: Repeated identical role-selection requests are handled safely and idempotently.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100015"
        await db["users"].delete_many({"phone_number": phone})
        user_res = await db["users"].insert_one({
            "name": "Repeat Role User",
            "phone_number": phone,
            "email": "repeat_role@example.com",
            "phone_verified": True,
            "hashed_password": get_password_hash("Password@123"),
            "role": None
        })
        token = create_access_token(subject=str(user_res.inserted_id))

        # First submission
        res1 = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res1.status_code == 200
        assert res1.json()["role"] == "businessman"

        # Duplicate submission (e.g. double click or retry)
        res2 = await ac.post(
            "/api/v1/auth/select-role",
            json={"role": "businessman"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res2.status_code == 200
        assert res2.json()["role"] == "businessman"
        assert res2.json()["success"] is True

async def test_req_16_regression_existing_msg91_and_security(mock_sms_service):
    """
    Req 16: Regression tests for existing MSG91 authentication and security constraints.
    - Password and phone verification cannot be bypassed.
    - Sensitive details (passwords, OTP hashes) are never exposed.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        phone = "+919811100016"
        await db["users"].delete_many({"phone_number": phone})
        await db["otps"].delete_many({"phone_number": phone})

        # Signup
        await ac.post("/api/v1/auth/signup", json={
            "name": "Regression User",
            "phone_number": phone,
            "email": "regression@example.com",
            "password": "Password@123"
        })

        # Wrong password fails
        bad_pw = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "WrongPassword@123"
        })
        assert bad_pw.status_code == 401

        # Correct password triggers SMS OTP
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 403
        assert mock_sms_service.called

        # DB has hashed OTP, not plain
        otp_doc = await db["otps"].find_one({"phone_number": phone})
        assert "otp_hash" in otp_doc
        assert otp_doc.get("otp") is None

        # Verify response never leaks hashed_password or sensitive internals
        await db["otps"].update_one({"phone_number": phone}, {"$set": {"otp_hash": get_password_hash("999888")}})
        v_res = await ac.post("/api/v1/auth/verify-otp", json={"phone_number": phone, "otp": "999888"})
        assert v_res.status_code == 200
        user_body = v_res.json()["user"]
        assert "hashed_password" not in user_body
        assert "password" not in user_body
