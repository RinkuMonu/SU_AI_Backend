import io
import uuid
import random
import pytest
from bson import ObjectId
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token

pytestmark = pytest.mark.asyncio

_phone_counter = 7000


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


async def create_user(role: str = "business", name: str = "Test User"):
    global _phone_counter
    _phone_counter += 1
    db = get_database()
    user_id = ObjectId()
    email = f"onboarding_user_{uuid.uuid4().hex[:8]}@example.com"
    phone = f"+919{random.randint(10000000, 99999999)}"

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
    return {"Authorization": f"Bearer {token}", "user_id": str(user_id)}


# ── 1. Role Selection Tests ──
async def test_role_selection_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/onboarding/role", json={"role": "business"})
        assert res.status_code == 401


async def test_role_selection_valid_business():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/onboarding/role", json={"role": "business"}, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["role"] == "business"
        assert data["next_step"] == "online_presence"


async def test_role_selection_valid_influencer():
    user = await create_user(role="influencer")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/onboarding/role", json={"role": "influencer"}, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["role"] == "influencer"
        assert data["next_step"] == "influencer_profile"


async def test_role_selection_rejects_invalid_roles():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for invalid in ["admin", "user_creator", "creator", "random_role", "personal"]:
            res = await ac.post("/api/v1/onboarding/role", json={"role": invalid}, headers=headers)
            assert res.status_code == 400
            assert "Invalid role" in (res.json().get("detail") or str(res.json()))


# ── 2. Business Step 1: Online Presence ──
async def test_online_presence_validation():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Empty presence rejected
        res = await ac.put("/api/v1/business-profile/online-presence", json={"presence_types": []}, headers=headers)
        assert res.status_code in [400, 422]

        # 'none' mutually exclusive check
        res = await ac.put(
            "/api/v1/business-profile/online-presence",
            json={"presence_types": ["none", "website"]},
            headers=headers
        )
        assert res.status_code in [400, 422]

        # Valid multi-presence
        res = await ac.put(
            "/api/v1/business-profile/online-presence",
            json={"presence_types": ["website", "google_maps"]},
            headers=headers
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "business_link"
        assert "website" in data["presence_types"]

        # Valid 'none' presence routes directly to business_details
        res = await ac.put(
            "/api/v1/business-profile/online-presence",
            json={"presence_types": ["none"]},
            headers=headers
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "business_details"


# ── 3. Business Step 2: Links CRUD & SSRF Protection ──
async def test_business_links_crud_and_ssrf():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # SSRF Protection: localhost blocked
        res = await ac.post(
            "/api/v1/business-profile/links",
            json={"type": "website", "url": "http://localhost:8080/admin"},
            headers=headers
        )
        assert res.status_code == 400

        # SSRF Protection: loopback 127.0.0.1 blocked
        res = await ac.post(
            "/api/v1/business-profile/links",
            json={"type": "website", "url": "http://127.0.0.1:8000/secret"},
            headers=headers
        )
        assert res.status_code == 400

        # Add valid link
        res = await ac.post(
            "/api/v1/business-profile/links",
            json={"type": "website", "url": "https://dhandagrow.com"},
            headers=headers
        )
        assert res.status_code == 201
        link_data = res.json()["data"]
        link_id = link_data["link_id"]
        assert link_data["url"] == "https://dhandagrow.com"

        # Duplicate link prevented
        res_dup = await ac.post(
            "/api/v1/business-profile/links",
            json={"type": "website", "url": "https://dhandagrow.com"},
            headers=headers
        )
        assert res_dup.status_code == 409

        # List links
        res_list = await ac.get("/api/v1/business-profile/links", headers=headers)
        assert res_list.status_code == 200
        assert len(res_list.json()["data"]) >= 1

        # Update link
        res_update = await ac.patch(
            f"/api/v1/business-profile/links/{link_id}",
            json={"platform": "official_store"},
            headers=headers
        )
        assert res_update.status_code == 200

        # Delete link
        res_del = await ac.delete(f"/api/v1/business-profile/links/{link_id}", headers=headers)
        assert res_del.status_code == 200


# ── 4. Business Step 3: Auto-Fetch & Details ──
async def test_business_autofetch_and_details():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create link
        res_link = await ac.post(
            "/api/v1/business-profile/links",
            json={"type": "website", "url": "https://example.com"},
            headers=headers
        )
        link_id = res_link.json()["data"]["link_id"]

        # Trigger fetch
        res_fetch = await ac.post(f"/api/v1/business-profile/links/{link_id}/fetch", headers=headers)
        assert res_fetch.status_code == 200

        # Check extracted details
        res_extracted = await ac.get("/api/v1/business-profile/extracted-details", headers=headers)
        assert res_extracted.status_code == 200

        # Confirm and update details
        res_details = await ac.patch(
            "/api/v1/business-profile/details",
            json={
                "business_name": "Unique Enterprises",
                "category": "Retail & Fashion",
                "description": "Leading manufacturer of custom clothing in Jaipur",
                "city": "Jaipur",
                "country": "India"
            },
            headers=headers
        )
        assert res_details.status_code == 200
        assert res_details.json()["data"]["business_name"] == "Unique Enterprises"


# ── 5. Business Step 5: Photos Upload & List ──
async def test_business_photos_upload():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        file_content = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00"  # mock jpeg bytes
        files = {"file": ("storefront.jpg", io.BytesIO(file_content), "image/jpeg")}
        data = {"caption": "Storefront Entrance", "is_primary": "true"}

        res = await ac.post("/api/v1/business-profile/photos", files=files, data=data, headers=headers)
        assert res.status_code == 201
        photo = res.json()["data"]
        photo_id = photo["photo_id"]
        assert photo["caption"] == "Storefront Entrance"

        # Get photos
        res_list = await ac.get("/api/v1/business-profile/photos", headers=headers)
        assert res_list.status_code == 200
        assert len(res_list.json()["data"]) >= 1

        # Delete photo
        res_del = await ac.delete(f"/api/v1/business-profile/photos/{photo_id}", headers=headers)
        assert res_del.status_code == 200


# ── 6. Business Step 6: Social Accounts ──
async def test_business_social_accounts():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/business-profile/social-accounts/connect",
            json={
                "platform": "instagram",
                "access_token": "EAAX_mock_secret_token",
                "account_id": "1784140012345",
                "account_name": "@unique_jaipur"
            },
            headers=headers
        )
        assert res.status_code == 200

        # List socials
        res_list = await ac.get("/api/v1/business-profile/social-accounts", headers=headers)
        assert res_list.status_code == 200
        accounts = res_list.json()["data"]
        assert len(accounts) >= 1
        assert accounts[0]["platform"] == "instagram"

        # Disconnect
        res_disc = await ac.delete("/api/v1/business-profile/social-accounts/instagram", headers=headers)
        assert res_disc.status_code == 200


# ── 7. Business Step 7 & 8: AI Photos & Comparison ──
async def test_ai_photos_and_profile_comparison():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # AI Photos
        res_ai = await ac.post(
            "/api/v1/business-profile/ai-photos/generate",
            json={"prompt": "Luxury storefront", "style": "editorial"},
            headers=headers
        )
        assert res_ai.status_code == 200
        data_ai = res_ai.json()
        assert len(data_ai["concepts"]) == 3
        assert len(data_ai["variations"]) == 2

        # Profile comparison score
        res_comp = await ac.get("/api/v1/business-profile/comparison", headers=headers)
        assert res_comp.status_code == 200
        data_comp = res_comp.json()
        assert 0 <= data_comp["overall_score"] <= 100
        assert data_comp["grade"] in ["Excellent", "Good", "Average", "Incomplete"]


# ── 8. Rating & Subscription ──
async def test_rating_and_subscription():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Rating with feedback
        res_rate = await ac.post(
            "/api/v1/onboarding/rating",
            json={"rating": 5, "feedback": "Super fast and intuitive flow!"},
            headers=headers
        )
        assert res_rate.status_code == 200

        # Subscription summary & plan select
        res_sub = await ac.get("/api/v1/business-profile/subscription", headers=headers)
        assert res_sub.status_code == 200

        res_select = await ac.post(
            "/api/v1/business-profile/subscription/select-plan",
            json={"plan_id": "BUSINESS_PRO", "billing_cycle": "monthly"},
            headers=headers
        )
        assert res_select.status_code == 200
        assert res_select.json()["plan_id"] == "BUSINESS_PRO"


# ── 9. Influencer Onboarding Flow ──
async def test_influencer_onboarding_flow():
    user = await create_user(role="influencer")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Get empty profile
        res_me = await ac.get("/api/v1/influencer-profile/me", headers=headers)
        assert res_me.status_code == 200

        # Update influencer details
        res_update = await ac.patch(
            "/api/v1/influencer-profile/details",
            json={
                "creator_name": "Riya Fashion Influencer",
                "bio": "Top Indian lifestyle & festive fashion creator.",
                "niche": ["Fashion", "Lifestyle", "Beauty"],
                "city": "Mumbai",
                "preferred_language": "Hinglish"
            },
            headers=headers
        )
        assert res_update.status_code == 200
        assert res_update.json()["data"]["username"] == "Riya Fashion Influencer"

        # Connect social account
        res_social = await ac.post(
            "/api/v1/influencer-profile/social-accounts/connect",
            json={
                "platform": "instagram",
                "access_token": "EAAX_influencer_token",
                "account_id": "17849999",
                "account_name": "@riya_styles"
            },
            headers=headers
        )
        assert res_social.status_code == 200

        # Save media kit
        res_mk = await ac.post(
            "/api/v1/influencer-profile/media-kit",
            json={
                "rates": {"reel_post": 25000.0, "story_mention": 5000.0},
                "contact_email": "riya.collabs@example.com",
                "top_content_links": ["https://instagram.com/p/mock1"]
            },
            headers=headers
        )
        assert res_mk.status_code == 200

        # Check completion
        res_comp = await ac.get("/api/v1/influencer-profile/completion", headers=headers)
        assert res_comp.status_code == 200
        assert res_comp.json()["completion_percentage"] > 0


# ── 10. Role Separation Enforcement ──
async def test_influencer_cannot_access_business_routes():
    user = await create_user(role="influencer")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.put(
            "/api/v1/business-profile/online-presence",
            json={"presence_types": ["website"]},
            headers=headers
        )
        assert res.status_code == 403


async def test_business_cannot_access_influencer_routes():
    user = await create_user(role="business")
    headers = {"Authorization": user["Authorization"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/influencer-profile/me", headers=headers)
        assert res.status_code == 403


# ── 11. Onboarding Progress API ──
async def test_onboarding_progress_api():
    biz_user = await create_user(role="business")
    inf_user = await create_user(role="influencer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Business user progress
        res_biz = await ac.get("/api/v1/onboarding/progress", headers={"Authorization": biz_user["Authorization"]})
        assert res_biz.status_code == 200
        data_biz = res_biz.json()
        assert data_biz["role"] == "business"
        assert "role_selection" in data_biz["completed_steps"]

        # Influencer user progress
        res_inf = await ac.get("/api/v1/onboarding/progress", headers={"Authorization": inf_user["Authorization"]})
        assert res_inf.status_code == 200
        data_inf = res_inf.json()
        assert data_inf["role"] == "influencer"
        assert "role_selection" in data_inf["completed_steps"]
