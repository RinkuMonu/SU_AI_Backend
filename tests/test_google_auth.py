import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from bson import ObjectId
from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import get_password_hash, create_access_token
from app.services.google_service import GoogleService
from app.services.sms_service import SMSService

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_sms_service():
    """Mock SMS delivery for unit testing — no real SMS calls."""
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"type": "success", "request_id": "mock_req_12345"}
        yield mock_send


@pytest.fixture(autouse=True)
async def db_fixture():
    connect_to_mongo()
    db = get_database()
    # Clean up test accounts before test
    test_pattern = {"$regex": r".*@example\.com|.*@google-test\.com"}
    await db["users"].delete_many({"email": test_pattern, "email": {"$ne": "admin@example.com"}})
    await db["pending_users"].delete_many({"email": test_pattern})
    await db["otps"].delete_many({})
    await db["phone_verifications"].delete_many({})
    await db["refresh_sessions"].delete_many({})
    yield db
    # Clean up after test
    if db is not None:
        await db["users"].delete_many({"email": test_pattern, "email": {"$ne": "admin@example.com"}})
        await db["pending_users"].delete_many({"email": test_pattern})
        await db["otps"].delete_many({})
        await db["phone_verifications"].delete_many({})
        await db["refresh_sessions"].delete_many({})


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# =====================================================================
# 1. Separate Login vs Registration: Unregistered User Login Rejection
# =====================================================================
async def test_unregistered_google_user_login_rejected(client, db_fixture):
    """
    Test: Unregistered Google user attempts to log in via /api/v1/auth/google/login (mode='login').
    Expectations:
      - HTTP 404 Not Found returned.
      - Detail: 'No account found with this Google email. Please register first.'
      - No account is created in MongoDB 'users' or 'pending_users'.
    """
    mock_profile = {
        "sub": "google-sub-unregistered",
        "email": "unregistered@google-test.com",
        "name": "Unregistered Tester",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {
            "access_token": "mock_unregistered_token",
            "mode": "login"
        }
        res = await client.post("/api/v1/auth/google/login", json=payload)
        assert res.status_code == 404
        assert "Please register first" in res.json()["detail"]

        # Confirm no account was created in MongoDB
        db_user = await db_fixture["users"].find_one({"email": "unregistered@google-test.com"})
        assert db_user is None
        pending = await db_fixture["pending_users"].find_one({"email": "unregistered@google-test.com"})
        assert pending is None


# =====================================================================
# 2. New Google User Registration (mode='signup', phone_verified=False)
# =====================================================================
async def test_new_google_user_registration(client, db_fixture):
    """
    Test: New Google user registers via /api/v1/auth/google/login with mode='signup'.
    Expectations:
      - Account created directly in canonical 'users' collection (not pending_users).
      - email_verified is True (Google-verified).
      - phone_verified is False (independent verification required).
      - role is None, requires_role_selection is True, dashboard_route is '/select-role'.
      - Refresh session and valid JWT tokens are issued.
      - Free subscription is automatically provisioned.
    """
    mock_profile = {
        "sub": "google-sub-10001",
        "email": "newgoogleuser@google-test.com",
        "given_name": "Arjun",
        "family_name": "Sharma",
        "name": "Arjun Sharma",
        "picture": "https://lh3.googleusercontent.com/a/mock_arjun.jpg",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {
            "access_token": "mock_google_access_token_10001",
            "phone_number": "+91 98765 43211",
            "accountType": "business",
            "mode": "signup"
        }
        res = await client.post("/api/v1/auth/google/login", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["success"] is True
        assert "access_token" in data
        assert data["requires_role_selection"] is True
        assert data["dashboard_route"] == "/select-role"
        assert data["role"] is None

        # Verify response user structure
        user_res = data["user"]
        assert user_res["email"] == "newgoogleuser@google-test.com"
        assert user_res["name"] == "Arjun Sharma"
        assert user_res["phone_number"] == "+919876543211"
        assert user_res["phone_verified"] is False  # Must NOT be verified solely by Google auth
        assert user_res["email_verified"] is True
        assert user_res["profileImageUrl"] == "https://lh3.googleusercontent.com/a/mock_arjun.jpg"

        # Check canonical users collection in MongoDB
        db_user = await db_fixture["users"].find_one({"email": "newgoogleuser@google-test.com"})
        assert db_user is not None
        assert db_user["googleId"] == "google-sub-10001"
        assert "google_id" not in db_user  # Redundant alias removed from canonical persistence
        assert "fullName" not in db_user
        assert "phone" not in db_user
        assert "contactNumber" not in db_user
        assert "emailVerified" not in db_user
        assert db_user["name"] == "Arjun Sharma"
        assert db_user["phone_number"] == "+919876543211"
        assert db_user["phone_verified"] is False
        assert db_user["email_verified"] is True
        assert "google" in db_user.get("authProviders", [])

        # Confirm nothing was staged in pending_users
        pending = await db_fixture["pending_users"].find_one({"email": "newgoogleuser@google-test.com"})
        assert pending is None

        # Check refresh session exists in MongoDB
        session = await db_fixture["refresh_sessions"].find_one({"userId": str(db_user["_id"])})
        assert session is not None
        assert session["isRevoked"] is False

        # Check auto-provisioned subscription
        sub = await db_fixture["subscriptions"].find_one({"$or": [{"user_id": str(db_user["_id"])}, {"userId": str(db_user["_id"])}]})
        assert sub is not None
        assert sub.get("plan_id") == "FREE" or str(sub.get("plan")).upper() == "FREE"


# =====================================================================
# 2. Returning Google User Login (Retains Role, requires_role_selection=False)
# =====================================================================
async def test_returning_google_user_login(client, db_fixture):
    """
    Test: Existing user with an assigned role logs in again via Google OAuth.
    Expectations:
      - Existing role ('influencer') is preserved, not overwritten.
      - requires_role_selection is False.
      - dashboard_route is '/influencer'.
    """
    # Pre-seed existing returning user with 'influencer' role
    now = datetime.now(timezone.utc)
    inserted = await db_fixture["users"].insert_one({
        "email": "returning@google-test.com",
        "googleId": "google-sub-20002",
        "name": "Pooja Varma",
        "role": "influencer",
        "phone_number": "+919876543212",
        "phone_verified": True,
        "email_verified": True,
        "authProviders": ["google"],
        "created_at": now,
        "updated_at": now
    })
    user_id = str(inserted.inserted_id)

    mock_profile = {
        "sub": "google-sub-20002",
        "email": "returning@google-test.com",
        "name": "Pooja Varma",
        "picture": "https://lh3.googleusercontent.com/a/mock_pooja.jpg",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {"access_token": "mock_access_token_returning"}
        res = await client.post("/api/v1/auth/google/login", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["success"] is True
        assert data["requires_role_selection"] is False
        assert data["dashboard_route"] == "/influencer"
        assert data["role"] == "influencer"
        assert data["user"]["phone_verified"] is True  # Preserved original verified status

        # Confirm DB role was not changed
        db_user = await db_fixture["users"].find_one({"_id": ObjectId(user_id)})
        assert db_user["role"] == "influencer"


# =====================================================================
# 3. Account Linking (Existing Email Account Links Google Credentials)
# =====================================================================
async def test_safe_account_linking_existing_email(client, db_fixture):
    """
    Test: User who originally signed up via email/password logs in with same email via Google.
    Expectations:
      - No duplicate user document is created.
      - Google credentials (googleId, google_id) and 'google' auth provider are linked.
      - Password and existing fields are retained.
    """
    now = datetime.now(timezone.utc)
    hashed_pw = get_password_hash("SecretPassword@123")
    inserted = await db_fixture["users"].insert_one({
        "email": "existinguser@google-test.com",
        "name": "Ramesh Kumar",
        "hashed_password": hashed_pw,
        "role": "businessman",
        "phone_number": "+919876543213",
        "phone_verified": True,
        "email_verified": True,
        "authProviders": ["email"],
        "created_at": now,
        "updated_at": now
    })
    user_id = str(inserted.inserted_id)

    mock_profile = {
        "sub": "google-sub-30003",
        "email": "existinguser@google-test.com",
        "name": "Ramesh Kumar",
        "picture": "https://lh3.googleusercontent.com/a/mock_ramesh.jpg",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {"access_token": "mock_access_token_link"}
        res = await client.post("/api/v1/auth/google/login", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["success"] is True
        assert data["role"] == "businessman"

        # Verify only 1 document in DB
        user_count = await db_fixture["users"].count_documents({"email": "existinguser@google-test.com"})
        assert user_count == 1

        db_user = await db_fixture["users"].find_one({"_id": ObjectId(user_id)})
        assert db_user["googleId"] == "google-sub-30003"
        assert "google_id" not in db_user
        assert "google" in db_user["authProviders"]
        assert "email" in db_user["authProviders"]
        assert db_user["hashed_password"] == hashed_pw  # Password intact


# =====================================================================
# 4. Duplicate Phone Collision Prevention
# =====================================================================
async def test_duplicate_phone_collision_rejection(client, db_fixture):
    """
    Test: New Google user attempts to register with a phone already owned by another user.
    Expectations:
      - HTTP 400 Bad Request returned with collision message.
      - No account created.
    """
    # User A owns +919876543214
    await db_fixture["users"].insert_one({
        "email": "usera@google-test.com",
        "name": "User Alpha",
        "phone_number": "+919876543214",
        "phone_verified": True,
        "role": "businessman"
    })

    # User B tries to register with User A's phone
    mock_profile = {
        "sub": "google-sub-40004",
        "email": "userb@google-test.com",
        "name": "User Beta",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {
            "access_token": "mock_access_token_b",
            "phone_number": "+91 98765 43214",
            "mode": "signup"
        }
        res = await client.post("/api/v1/auth/google/login", json=payload)
        assert res.status_code == 400
        assert "already registered" in res.json()["detail"].lower()

        # Confirm User B was NOT inserted into users
        user_b = await db_fixture["users"].find_one({"email": "userb@google-test.com"})
        assert user_b is None


# =====================================================================
# 5. Google Signup Alias Endpoint (/api/v1/auth/google/signup)
# =====================================================================
async def test_google_signup_endpoint(client, db_fixture):
    """
    Test: POST /api/v1/auth/google/signup delegates directly to google_login with mode='signup'.
    Expectations:
      - HTTP 201 Created status.
      - User registered directly into 'users'.
      - phone_verified is False.
    """
    mock_profile = {
        "sub": "google-sub-50005",
        "email": "signupuser@google-test.com",
        "name": "Signup Tester",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        payload = {
            "access_token": "mock_token_signup",
            "phone_number": "+91 98765 43215"
        }
        res = await client.post("/api/v1/auth/google/signup", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert data["requires_role_selection"] is True
        assert data["user"]["phone_verified"] is False


# =====================================================================
# 6. Role Selection Flow for Google Users
# =====================================================================
async def test_role_selection_after_google_registration(client, db_fixture):
    """
    Test: User registers with Google, receives JWT, then calls /api/v1/auth/select-role.
    Expectations:
      - Role is updated from None to 'businessman'.
      - phone_verified remains False (does NOT get falsely flipped to True).
      - Idempotent: re-selecting 'businessman' succeeds safely.
      - Rejecting role change: selecting 'influencer' afterwards fails with 400.
      - Escalation rejection: selecting 'admin' fails with 403.
    """
    mock_profile = {
        "sub": "google-sub-60006",
        "email": "roleselect@google-test.com",
        "name": "Role Candidate",
        "email_verified": True
    }

    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_info.return_value = mock_profile

        reg_res = await client.post("/api/v1/auth/google/signup", json={
            "access_token": "mock_token_roleselect",
            "phone_number": "+91 98765 43216"
        })
        assert reg_res.status_code == 201
        auth_data = reg_res.json()
        token = auth_data["access_token"]
        user_id = auth_data["user"]["id"]

        headers = {"Authorization": f"Bearer {token}"}

        # 1. Select role 'businessman'
        role_res = await client.post("/api/v1/auth/select-role", json={"role": "businessman"}, headers=headers)
        assert role_res.status_code == 200
        role_data = role_res.json()
        assert role_data["role"] == "businessman"
        assert role_data["phone_verified"] is False  # Invariant: phone_verified is preserved

        # Verify DB
        db_user = await db_fixture["users"].find_one({"_id": ObjectId(user_id)})
        assert db_user["role"] == "businessman"
        assert db_user["phone_verified"] is False

        # 2. Check dashboard-route endpoint
        route_res = await client.get("/api/v1/auth/dashboard-route", headers=headers)
        assert route_res.status_code == 200
        assert route_res.json()["dashboard_route"] == "/dashboard/business"

        # 3. Idempotent duplicate submission
        dup_res = await client.post("/api/v1/auth/select-role", json={"role": "businessman"}, headers=headers)
        assert dup_res.status_code == 200

        # 4. Attempt to change to 'influencer' must be rejected
        change_res = await client.post("/api/v1/auth/select-role", json={"role": "influencer"}, headers=headers)
        assert change_res.status_code == 400
        assert "already been set" in change_res.json()["detail"].lower()

        # 5. Attempt admin escalation must be forbidden
        admin_res = await client.post("/api/v1/auth/select-role", json={"role": "admin"}, headers=headers)
        assert admin_res.status_code == 403


# =====================================================================
# 7. OAuth Code Exchange Flow via Google Connect & Callback
# =====================================================================
async def test_google_connect_and_code_exchange(client, db_fixture):
    """
    Test:
      - /api/v1/auth/google/connect returns valid authorization URL.
      - /api/v1/auth/google/login with 'code' exchanges code for token and registers user.
    """
    connect_res = await client.get("/api/v1/auth/google/connect")
    assert connect_res.status_code == 200
    connect_data = connect_res.json()
    assert "authorization_url" in connect_data
    assert "accounts.google.com" in connect_data["authorization_url"]

    mock_token_resp = {
        "access_token": "mock_exchanged_access_token",
        "id_token": "mock_exchanged_id_token",
        "token_type": "Bearer",
        "expires_in": 3600
    }
    mock_profile = {
        "sub": "google-sub-70007",
        "email": "codeexchange@google-test.com",
        "name": "Code Exchanger",
        "email_verified": True
    }

    with patch.object(GoogleService, "exchange_code_for_token", new_callable=AsyncMock) as mock_exchange, \
         patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_info:
        mock_exchange.return_value = mock_token_resp
        mock_info.return_value = mock_profile

        res = await client.post("/api/v1/auth/google/signup", json={"code": "mock_auth_code_xyz"})
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert data["user"]["email"] == "codeexchange@google-test.com"


# =====================================================================
# 8. Preservation of Password Login & OTP Verification Endpoints
# =====================================================================
async def test_password_login_and_otp_endpoints_preserved(client, db_fixture):
    """
    Test: Ensure existing password authentication and SMS OTP endpoints remain 100% operational.
    """
    # 1. Password login test
    hashed_pwd = get_password_hash("ValidPass@123")
    await db_fixture["users"].insert_one({
        "email": "passwordlogin@google-test.com",
        "name": "Password User",
        "hashed_password": hashed_pwd,
        "role": "businessman",
        "phone_number": "+919876543218",
        "phone_verified": True,
        "email_verified": True,
        "authProviders": ["email"]
    })

    login_res = await client.post("/api/v1/auth/login", json={
        "email": "passwordlogin@google-test.com",
        "password": "ValidPass@123"
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

    # 2. OTP send test
    otp_res = await client.post("/api/v1/auth/send-otp", json={
        "phone_number": "+919876543219"
    })
    assert otp_res.status_code == 200
    assert otp_res.json().get("status") == "success" or otp_res.json().get("success") is True

    # 3. OTP verify test with pre-seeded OTP
    await db_fixture["otps"].update_one(
        {"phone_number": "+919876543219"},
        {"$set": {"otp_hash": get_password_hash("654321"), "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)}},
        upsert=True
    )
    # Also pre-seed a user for this phone
    await db_fixture["users"].insert_one({
        "phone_number": "+919876543219",
        "name": "OTP User",
        "phone_verified": False,
        "role": None
    })

    verify_res = await client.post("/api/v1/auth/verify-otp", json={
        "phone_number": "+919876543219",
        "otp": "654321"
    })
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert "access_token" in verify_data
    # Upon successful OTP verification, phone_verified is True
    assert verify_data["user"]["phone_verified"] is True


# =====================================================================
# 10. Canonical Fields and Migration Reconciliation Test
# =====================================================================
async def test_canonical_fields_and_migration_reconciliation(db_fixture):
    """
    Test: Simulates legacy documents with duplicate aliases and verifies that
    the migration script removes redundant fields from persistence while
    preserving canonical fields and index structure.
    """
    from scripts.migrate_google_auth_and_indexes import run_migration

    # Seed legacy document containing duplicate fields
    test_id = ObjectId()
    await db_fixture["users"].insert_one({
        "_id": test_id,
        "email": "legacy_migration@test.com",
        "google_id": "legacy-gid-999",
        "googleId": "legacy-gid-999",
        "fullName": "Legacy User",
        "name": "Legacy User",
        "phone": "+919876543299",
        "contactNumber": "+919876543299",
        "phone_number": "+919876543299",
        "phone_verified": False,
        "emailVerified": True,
        "email_verified": True
    })

    # Run migration
    await run_migration()

    # Verify document in MongoDB
    migrated = await db_fixture["users"].find_one({"_id": test_id})
    assert migrated is not None
    # Canonical fields must be preserved
    assert migrated["googleId"] == "legacy-gid-999"
    assert migrated["name"] == "Legacy User"
    assert migrated["phone_number"] == "+919876543299"
    assert migrated["email_verified"] is True
    assert migrated["phone_verified"] is False

    # Redundant duplicate fields must be strictly UNSET
    assert "google_id" not in migrated
    assert "fullName" not in migrated
    assert "phone" not in migrated
    assert "contactNumber" not in migrated
    assert "emailVerified" not in migrated
    assert "emailVerifiedAt" not in migrated

    # Indexes check: google_id_1_sparse must not exist
    indexes = await db_fixture["users"].index_information()
    assert "google_id_1_sparse" not in indexes
    assert "googleId_1_sparse" in indexes
