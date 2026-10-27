import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import get_password_hash, create_access_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    db = get_database()
    pattern = {"$regex": r".*@onboarding-test\.com"}
    await db["users"].delete_many({"email": pattern})
    await db["pending_users"].delete_many({"email": pattern})
    await db["businesses"].delete_many({"$or": [{"owner_id": {"$exists": True}}, {"ownerId": {"$exists": True}}]})
    yield db
    await db["users"].delete_many({"email": pattern})
    await db["pending_users"].delete_many({"email": pattern})


async def create_user_helper(db, email: str, role: str = None, onboarding_completed: bool = False, online_presence: str = None, step: int = 1):
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Onboarding Tester",
        "email": email,
        "phone_number": f"+9199{str(uid)[-8:]}",
        "phone_verified": True,
        "email_verified": True,
        "hashed_password": get_password_hash("Secret@123"),
        "role": role,
        "onboardingCompleted": onboarding_completed,
        "onboarding_step": step,
        "online_presence": online_presence,
        "created_at": datetime.now(timezone.utc)
    }
    if onboarding_completed:
        doc["onboarding_completed_at"] = datetime.now(timezone.utc)
        doc["onboarding_status"] = "completed"
    elif online_presence:
        doc["onboarding_status"] = "in_progress"
    else:
        doc["onboarding_status"] = "not_started"

    await db["users"].insert_one(doc)
    token = create_access_token(subject=str(uid))
    return str(uid), token, doc


# ==============================================================================
# 1. New Signup -> Role Selection -> Not Started -> Needs Online Presence
# ==============================================================================
async def test_new_user_onboarding_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        db = get_database()
        email = "new_businessman@onboarding-test.com"
        phone = "+919811122334"
        await db["users"].delete_many({"$or": [{"email": email}, {"phone_number": phone}]})

        # Step 1: Signup
        signup_res = await ac.post("/api/v1/auth/signup", json={
            "name": "Rajesh Kumar",
            "email": email,
            "phone_number": phone,
            "password": "Password@123",
            "confirmPassword": "Password@123"
        })
        assert signup_res.status_code == 201
        signup_data = signup_res.json()
        assert signup_data["onboardingCompleted"] is False
        assert signup_data["onboarding_status"] == "not_started"
        assert signup_data["can_access_dashboard"] is False
        assert signup_data["next_step"] == "role_selection"

        # Mark phone as verified for test login
        await db["users"].update_one({"email": email}, {"$set": {"phone_verified": True}})

        # Step 2: Login
        login_res = await ac.post("/api/v1/auth/login", json={
            "phone_number": phone,
            "password": "Password@123"
        })
        assert login_res.status_code == 200
        data = login_res.json()
        token = data["access_token"]
        assert data["requires_role_selection"] is True
        assert data["can_access_dashboard"] is False
        assert data["onboarding_status"] == "not_started"
        assert data["next_step"] == "role_selection"

        headers = {"Authorization": f"Bearer {token}"}

        # Step 3: Select Businessman Role
        role_res = await ac.post("/api/v1/auth/select-role", json={"role": "businessman"}, headers=headers)
        assert role_res.status_code == 200
        role_data = role_res.json()
        assert role_data["role"] == "businessman"
        assert role_data["can_access_dashboard"] is False
        assert role_data["onboarding_status"] == "not_started"
        assert role_data["next_step"] == "online_presence"

        # Step 4: Check /onboarding/status -> indicates step 1 online presence pending
        status_res = await ac.get("/api/v1/onboarding/status", headers=headers)
        assert status_res.status_code == 200
        st = status_res.json()
        assert st["onboarding_completed"] is False
        assert st["onboardingCompleted"] is False
        assert st["can_access_dashboard"] is False
        assert st["next_step"] == "online_presence"
        assert st["online_presence"] is None


# ==============================================================================
# 2. Saving and Restoring All Supported Online Presence Options
# ==============================================================================
@pytest.mark.parametrize("presence_option", [
    "website",
    "google_maps",
    "marketplace_seller",
    "no_online_presence",
    "wholesale_b2b",
    "other",
    "something_else"
])
async def test_save_and_restore_online_presence_options(presence_option):
    db = get_database()
    email = f"opt_{presence_option}@onboarding-test.com"
    uid, token, _ = await create_user_helper(db, email=email, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Submit selection via POST /api/v1/onboarding/online-presence
        res = await ac.post("/api/v1/onboarding/online-presence", json={
            "online_presence": presence_option,
            "google_maps_url": "https://maps.google.com/?q=Test" if presence_option == "google_maps" else None,
            "website_url": "https://example.com" if presence_option == "website" else None
        }, headers=headers)

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["online_presence"] == presence_option
        assert body["onboarding_step"] == 2
        assert body["onboarding_status"] == "in_progress"
        assert body["next_step"] == "brand_kit"
        assert body["can_access_dashboard"] is False

        # Verify DB persistence
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc["online_presence"] == presence_option
        assert user_doc["onboarding_step"] == 2
        assert user_doc["onboarding_status"] == "in_progress"

        bus_doc = await db["businesses"].find_one({"owner_id": uid})
        assert bus_doc is not None
        assert bus_doc["online_presence"] == presence_option

        # Verify restoring via GET /api/v1/onboarding/online-presence
        get_res = await ac.get("/api/v1/onboarding/online-presence", headers=headers)
        assert get_res.status_code == 200
        get_body = get_res.json()
        assert get_body["online_presence"] == presence_option
        assert get_body["onboarding_step"] == 2
        assert get_body["onboarding_status"] == "in_progress"
        assert get_body["next_step"] == "brand_kit"


# ==============================================================================
# 3. Invalid Online Presence Validation
# ==============================================================================
async def test_invalid_online_presence_rejected():
    db = get_database()
    uid, token, _ = await create_user_helper(db, email="invalid_presence@onboarding-test.com", role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Invalid option
        res = await ac.post("/api/v1/onboarding/online-presence", json={
            "online_presence": "flying_drones"
        }, headers=headers)
        assert res.status_code == 400
        assert "Invalid online_presence selection" in res.json()["detail"]

        # 2. Empty string
        res_empty = await ac.post("/api/v1/onboarding/online-presence", json={
            "online_presence": "   "
        }, headers=headers)
        assert res_empty.status_code == 400

        # 3. Via PATCH /progress with invalid value
        patch_res = await ac.patch("/api/v1/onboarding/progress", json={
            "online_presence": "teleportation"
        }, headers=headers)
        assert patch_res.status_code == 400


# ==============================================================================
# 4. Incomplete vs Completed User Login and Dashboard Access
# ==============================================================================
async def test_incomplete_user_login_resumes_pending_step():
    db = get_database()
    email = "incomplete_user@onboarding-test.com"
    # User selected google_maps, step 2 pending
    uid, token, doc = await create_user_helper(
        db, email=email, role="businessman", onboarding_completed=False, online_presence="google_maps", step=2
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Login
        res = await ac.post("/api/v1/auth/login", json={
            "email": email,
            "password": "Secret@123"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["requires_role_selection"] is False
        assert data["can_access_dashboard"] is False
        assert data["onboarding_status"] == "in_progress"
        assert data["online_presence"] == "google_maps"
        assert data["onboarding_step"] == 2
        assert data["next_step"] == "brand_kit"

        headers = {"Authorization": f"Bearer {token}"}

        # Protected Dashboard Access Guard rejects incomplete onboarding
        guard_res = await ac.get("/api/v1/auth/dashboard/access", headers=headers)
        assert guard_res.status_code == 403
        assert "Onboarding incomplete" in guard_res.json()["detail"]

        # Dashboard route response returns can_access_dashboard: False, requires_onboarding: True
        route_res = await ac.get("/api/v1/auth/dashboard-route", headers=headers)
        assert route_res.status_code == 200
        r_data = route_res.json()
        assert r_data["can_access_dashboard"] is False
        assert r_data["requires_onboarding"] is True
        assert r_data["next_step"] == "brand_kit"


async def test_completed_user_login_reaches_dashboard():
    db = get_database()
    email = "completed_user@onboarding-test.com"
    uid, token, doc = await create_user_helper(
        db, email=email, role="businessman", onboarding_completed=True, online_presence="website", step=3
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Login
        res = await ac.post("/api/v1/auth/login", json={
            "email": email,
            "password": "Secret@123"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["can_access_dashboard"] is True
        assert data["onboarding_status"] == "completed"
        assert data["next_step"] == "dashboard"
        assert data["onboardingCompleted"] is True

        headers = {"Authorization": f"Bearer {token}"}

        # Protected Dashboard Access Guard succeeds
        guard_res = await ac.get("/api/v1/auth/dashboard/access", headers=headers)
        assert guard_res.status_code == 200
        assert guard_res.json()["can_access_dashboard"] is True

        # /dashboard-route indicates completed access
        route_res = await ac.get("/api/v1/auth/dashboard-route", headers=headers)
        assert route_res.status_code == 200
        r_data = route_res.json()
        assert r_data["can_access_dashboard"] is True
        assert r_data["requires_onboarding"] is False
        assert r_data["next_step"] == "dashboard"


# ==============================================================================
# 5. Influencer Role Directly Accesses Creator Dashboard Without Business Onboarding
# ==============================================================================
async def test_influencer_role_direct_access():
    db = get_database()
    email = "influencer_user@onboarding-test.com"
    uid, token, doc = await create_user_helper(db, email=email, role="influencer", onboarding_completed=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Dashboard route
        dash_res = await ac.get("/api/v1/auth/dashboard-route", headers=headers)
        assert dash_res.status_code == 200
        d_data = dash_res.json()
        assert d_data["role"] == "influencer"
        assert d_data["dashboard_route"] == "/dashboard/creator"
        assert d_data["can_access_dashboard"] is True
        assert d_data["requires_onboarding"] is False
        assert d_data["next_step"] == "dashboard"


# ==============================================================================
# 6. Finalizing Onboarding via /complete
# ==============================================================================
async def test_complete_onboarding_endpoint():
    db = get_database()
    email = "finalize_user@onboarding-test.com"
    uid, token, doc = await create_user_helper(db, email=email, role="businessman", onboarding_completed=False, online_presence="marketplace_seller", step=3)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Complete onboarding
        comp_res = await ac.post("/api/v1/onboarding/complete", json={"notes": "All steps done"}, headers=headers)
        assert comp_res.status_code == 200
        assert comp_res.json()["success"] is True

        # Status check
        st_res = await ac.get("/api/v1/onboarding/status", headers=headers)
        assert st_res.status_code == 200
        st = st_res.json()
        assert st["onboarding_completed"] is True
        assert st["onboarding_status"] == "completed"
        assert st["can_access_dashboard"] is True
        assert st["next_step"] == "dashboard"
