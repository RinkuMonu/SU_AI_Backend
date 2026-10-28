import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import get_password_hash, create_access_token
from app.schemas.onboarding import SUPPORTED_BUSINESS_SERVICES, VALID_BUSINESS_SERVICE_IDS

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    db = get_database()
    pattern = {"$regex": r".*@services-test\.com"}
    await db["users"].delete_many({"email": pattern})
    await db["pending_users"].delete_many({"email": pattern})
    yield db
    await db["users"].delete_many({"email": pattern})
    await db["pending_users"].delete_many({"email": pattern})


async def create_user_helper(db, email: str, role: str = "businessman", step: int = 2, online_presence: str = "website"):
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Services Tester",
        "email": email,
        "phone_number": f"+9198{str(uid)[-8:]}",
        "phone_verified": True,
        "email_verified": True,
        "hashed_password": get_password_hash("Secret@123"),
        "role": role,
        "onboardingCompleted": False,
        "onboarding_step": step,
        "online_presence": online_presence,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(doc)
    token = create_access_token(subject=str(uid))
    return str(uid), token, doc


# ==============================================================================
# 0. Service Catalog Verification
# ==============================================================================
async def test_business_services_catalog():
    """Verify that the catalog returns all 7 supported business services."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/onboarding/services/catalog")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["count"] == 7
        service_ids = [s["id"] for s in data["services"]]
        expected_ids = [
            "automate_social_media",
            "marketing_video",
            "fashion_photoshoot",
            "product_photoshoot",
            "ai_website_builder",
            "leads_crm",
            "ai_marketing_agent",
        ]
        assert sorted(service_ids) == sorted(expected_ids)


# ==============================================================================
# 1. Saving One Selected Service
# ==============================================================================
async def test_save_single_service(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "single@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {"selectedServices": ["automate_social_media"]}
        res = await ac.post("/api/v1/onboarding/services", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["selected_services"] == ["automate_social_media"]
        assert data["selectedServices"] == ["automate_social_media"]
        assert data["count"] == 1
        assert len(data["services"]) == 1
        assert data["services"][0]["id"] == "automate_social_media"

        # Verify DB persistence in users collection
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc["selected_services"] == ["automate_social_media"]

        # Verify DB persistence in businesses collection
        bus_doc = await db["businesses"].find_one({"owner_id": uid})
        assert bus_doc["selected_services"] == ["automate_social_media"]
        assert len(bus_doc["service_details"]) == 1
        assert bus_doc["service_details"][0]["id"] == "automate_social_media"


# ==============================================================================
# 2. Saving Multiple Services
# ==============================================================================
async def test_save_multiple_services(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "multiple@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        chosen = ["automate_social_media", "marketing_video", "leads_crm"]
        payload = {"selectedServices": chosen}
        res = await ac.post("/api/v1/onboarding/services", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["selected_services"] == chosen
        assert data["count"] == 3
        returned_ids = [s["id"] for s in data["services"]]
        assert returned_ids == chosen

        # Verify DB persistence
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc["selected_services"] == chosen
        bus_doc = await db["businesses"].find_one({"owner_id": uid})
        assert bus_doc["selected_services"] == chosen


# ==============================================================================
# 3. Updating and Deselecting Previously Saved Services
# ==============================================================================
async def test_update_and_deselect_services(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "update@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Initial selection: 4 services
        initial = ["automate_social_media", "marketing_video", "fashion_photoshoot", "ai_marketing_agent"]
        res1 = await ac.post("/api/v1/onboarding/services", json={"selectedServices": initial}, headers=headers)
        assert res1.status_code == 200
        assert res1.json()["count"] == 4

        # Update: deselect fashion_photoshoot and ai_marketing_agent, add product_photoshoot (PUT endpoint test)
        updated = ["automate_social_media", "product_photoshoot"]
        res2 = await ac.put("/api/v1/onboarding/services", json={"selectedServices": updated}, headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["selected_services"] == updated
        assert data2["count"] == 2

        # Verify DB persistence reflects updated choice
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc["selected_services"] == updated
        bus_doc = await db["businesses"].find_one({"owner_id": uid})
        assert bus_doc["selected_services"] == updated


# ==============================================================================
# 4. Empty Selection Behavior (Clearing choices)
# ==============================================================================
async def test_empty_selection_clearing(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "empty@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # First save something
        await ac.post("/api/v1/onboarding/services", json={"selectedServices": ["leads_crm"]}, headers=headers)

        # Now pass empty list
        res = await ac.post("/api/v1/onboarding/services", json={"selectedServices": []}, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["selected_services"] == []
        assert data["count"] == 0
        assert data["services"] == []

        # Verify DB is now empty list
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc["selected_services"] == []


# ==============================================================================
# 5. Invalid Service IDs Rejection
# ==============================================================================
async def test_invalid_service_id_rejection(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "invalid@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Attempt to save an unknown service ID
        payload = {"selectedServices": ["automate_social_media", "invalid_super_service", "leads_crm"]}
        res = await ac.post("/api/v1/onboarding/services", json=payload, headers=headers)
        assert res.status_code == 400
        data = res.json()
        assert "Invalid business service 'invalid_super_service'" in data["detail"]

        # Ensure previous state wasn't corrupted
        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc.get("selected_services") is None


# ==============================================================================
# 6. Duplicate Service IDs Handling
# ==============================================================================
async def test_duplicate_service_ids_deduplication(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "dedup@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Duplicate IDs in request
        payload = {
            "selectedServices": [
                "marketing_video",
                "leads_crm",
                "marketing_video",
                "leads_crm",
                "ai_website_builder"
            ]
        }
        res = await ac.post("/api/v1/onboarding/services", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        # Should be deduped while maintaining order of first appearance
        expected = ["marketing_video", "leads_crm", "ai_website_builder"]
        assert data["selected_services"] == expected
        assert data["count"] == 3


# ==============================================================================
# 7. Unauthenticated Requests Rejection
# ==============================================================================
async def test_unauthenticated_requests():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. No auth header on POST
        res1 = await ac.post("/api/v1/onboarding/services", json={"selectedServices": ["marketing_video"]})
        assert res1.status_code == 401

        # 2. No auth header on GET
        res2 = await ac.get("/api/v1/onboarding/services")
        assert res2.status_code == 401

        # 3. Invalid token
        bad_headers = {"Authorization": "Bearer bad-token-12345"}
        res3 = await ac.post("/api/v1/onboarding/services", json={"selectedServices": ["marketing_video"]}, headers=bad_headers)
        assert res3.status_code == 401


# ==============================================================================
# 8. Retrieving Saved Selections After Refresh / Login
# ==============================================================================
async def test_retrieve_saved_selections_flow(setup_db):
    db = setup_db
    email = "restore@services-test.com"
    uid, token, _ = await create_user_helper(db, email)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        services_to_save = ["product_photoshoot", "ai_marketing_agent"]
        await ac.post("/api/v1/onboarding/services", json={"selectedServices": services_to_save}, headers=headers)

        # 1. Retrieve via GET /onboarding/services
        res1 = await ac.get("/api/v1/onboarding/services", headers=headers)
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1["selected_services"] == services_to_save
        assert d1["selectedServices"] == services_to_save
        assert d1["count"] == 2
        assert len(d1["services"]) == 2

        # 2. Retrieve via GET /onboarding/status (central status polled on refresh)
        res2 = await ac.get("/api/v1/onboarding/status", headers=headers)
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["selected_services"] == services_to_save
        assert d2["selectedServices"] == services_to_save

        # 3. Retrieve via GET /users/me
        res3 = await ac.get("/api/v1/users/me", headers=headers)
        assert res3.status_code == 200
        d3 = res3.json()["data"]
        assert d3["selected_services"] == services_to_save
        assert d3["selectedServices"] == services_to_save


# ==============================================================================
# 9. Confirming All Five Business-Source Flows Work Unchanged
# ==============================================================================
async def test_preservation_of_five_business_sources(setup_db):
    db = setup_db
    uid, token, _ = await create_user_helper(db, "sources@services-test.com")
    headers = {"Authorization": f"Bearer {token}"}

    five_sources = [
        ("website", {"website_url": "https://myshop.com"}),
        ("google_maps", {"google_maps_url": "https://maps.google.com/?q=Test+Shop"}),
        ("marketplace_seller", {"selected_platforms": ["amazon", "flipkart"]}),
        ("no_online_presence", {"business_name": "Local Store"}),
        ("wholesale_b2b", {"selected_platforms": ["indiamart", "udaan"]})
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Pre-set some business services
        await ac.post(
            "/api/v1/onboarding/services",
            json={"selectedServices": ["automate_social_media", "marketing_video"]},
            headers=headers
        )

        for source_type, extra_payload in five_sources:
            req_payload = {"online_presence": source_type, **extra_payload}
            res = await ac.post("/api/v1/onboarding/online-presence", json=req_payload, headers=headers)
            assert res.status_code == 200, f"Failed for source {source_type}: {res.text}"
            data = res.json()
            assert data["online_presence"] == source_type
            assert data["onboarding_status"] == "in_progress"

            # Check that services were preserved and NOT replaced by online_presence
            bus_doc = await db["businesses"].find_one({"owner_id": uid})
            assert bus_doc["online_presence"] == source_type
            assert bus_doc["selected_services"] == ["automate_social_media", "marketing_video"]

        # Verify GET /online-presence also returns both online_presence and selected_services
        res_get = await ac.get("/api/v1/onboarding/online-presence", headers=headers)
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["online_presence"] == "wholesale_b2b"
        assert get_data["selected_services"] == ["automate_social_media", "marketing_video"]
