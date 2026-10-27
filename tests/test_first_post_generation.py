import asyncio
import io
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from PIL import Image

from unittest.mock import patch

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token, get_password_hash
from app.services.first_post_service import FirstPostService
from app.services.platform_onboarding_service import PlatformOnboardingService


async def _mock_generate_post(*args, **kwargs):
    instruction = kwargs.get("additional_instruction") or ""
    return {
        "headline": "Handcrafted Luxury Launch",
        "caption": f"Experience authentic craftsmanship with our exclusive collection. {instruction}",
        "call_to_action": "Shop Now",
        "hashtags": ["#handcrafted", "#luxury", "#dhandagrow"],
        "creative_direction": "Clean high-contrast authentic photography",
        "image_url": "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b",
        "media_url": "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b",
    }


@pytest.fixture(autouse=True)
def ensure_db():
    connect_to_mongo()


@pytest.fixture(autouse=True)
def mock_gemini_post_generation():
    with patch("app.ai.services.post_generation.PostGenerationService.generate_post", side_effect=_mock_generate_post):
        yield


@pytest.fixture
async def free_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "First Post Free Tester",
        "email": f"fp_free_{str(uid)[-6:]}@test.com",
        "phone_number": f"+9198{str(uid)[-8:]}",
        "phone_verified": True,
        "email_verified": True,
        "hashed_password": get_password_hash("Secret@123"),
        "role": "businessman",
        "onboardingCompleted": False,
        "onboarding_step": 1,
        "online_presence": None,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(doc)
    # Free subscription
    await db["subscriptions"].insert_one({
        "user_id": str(uid),
        "plan_id": "FREE",
        "plan": "FREE",
        "status": "active",
        "credits_total": 5,
        "credits_remaining": 5,
        "created_at": datetime.now(timezone.utc)
    })
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, str(uid)


@pytest.fixture
async def paid_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "First Post Paid Tester",
        "email": f"fp_paid_{str(uid)[-6:]}@test.com",
        "phone_number": f"+9199{str(uid)[-8:]}",
        "phone_verified": True,
        "email_verified": True,
        "hashed_password": get_password_hash("Secret@123"),
        "role": "businessman",
        "onboardingCompleted": False,
        "onboarding_step": 1,
        "online_presence": None,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(doc)
    # Starter paid subscription
    await db["subscriptions"].insert_one({
        "user_id": str(uid),
        "plan_id": "STARTER",
        "plan": "STARTER",
        "status": "active",
        "credits_total": 100,
        "credits_remaining": 100,
        "created_at": datetime.now(timezone.utc)
    })
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, str(uid)


@pytest.fixture
async def other_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Unauthorized Intruder",
        "email": f"intruder_{str(uid)[-6:]}@test.com",
        "phone_number": f"+9191{str(uid)[-8:]}",
        "phone_verified": True,
        "email_verified": True,
        "hashed_password": get_password_hash("Secret@123"),
        "role": "businessman",
        "onboardingCompleted": False,
        "onboarding_step": 1,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(doc)
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, str(uid)


# -----------------------------------------------------------------------------
# 1. Business-presence types persistence (all 5 types)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_all_five_business_presence_types(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        presence_types = [
            ("website", {"website_url": "https://myshop.in"}),
            ("google_maps", {"google_maps_url": "https://maps.google.com/?cid=12345"}),
            ("marketplace_seller", {"selected_platforms": ["amazon", "flipkart"]}),
            ("no_online_presence", {}),
            ("wholesale_b2b", {"selected_platforms": ["indiamart", "tradeindia"]}),
        ]

        for p_type, extra in presence_types:
            payload = {"online_presence": p_type, **extra}
            res = await client.post("/api/v1/onboarding/online-presence", headers=headers, json=payload)
            assert res.status_code == 200, f"Failed for {p_type}: {res.text}"
            data = res.json()
            assert data["success"] is True
            assert data["online_presence"] == p_type
            assert data["onboarding_step"] >= 2
            assert data["onboarding_status"] == "in_progress"

        # Verify no duplicate business records were created
        db = get_database()
        b_count = await db["businesses"].count_documents({"$or": [{"owner_id": uid}, {"ownerId": uid}]})
        assert b_count == 1, "Only 1 business record should exist per user"


# -----------------------------------------------------------------------------
# 2. Multi-platform URL submission, SSRF protection & partial failure handling
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_platform_urls_and_partial_failure(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Submit Amazon (valid) and Flipkart (internal blocked SSRF target)
        payload = {
            "onboarding_source": "marketplace_seller",
            "selected_platforms": ["amazon", "flipkart"],
            "platform_urls": {
                "amazon": "https://www.amazon.in/shops/mybrand",
                "flipkart": "http://127.0.0.1:8000/internal-secrets"  # blocked target
            }
        }
        res = await client.post("/api/v1/onboarding/platforms", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["selected_platforms"] == ["amazon", "flipkart"]

        # Amazon URL is accepted and validated
        assert "amazon" in data["platform_urls"]
        assert data["platform_analysis_status"]["amazon"] in ["pending", "completed", "processing"]

        # Flipkart was blocked by SSRF safety, marked as failed without crashing the request
        assert "flipkart" in data["platform_urls"]
        assert data["platform_analysis_status"]["flipkart"] == "failed"

        # Retry flipkart with a valid public URL via dedicated analyze-url endpoint
        retry_res = await client.post(
            "/api/v1/onboarding/platforms/analyze-url",
            headers=headers,
            json={
                "platform_id": "flipkart",
                "url": "https://www.flipkart.com/seller/mybrand",
                "onboarding_source": "marketplace_seller"
            }
        )
        assert retry_res.status_code == 200
        retry_data = retry_res.json()
        assert retry_data["platform_id"] == "flipkart"
        assert retry_data["status"] in ["pending", "completed"]

        # Fetch state and verify Amazon was NOT erased by Flipkart retry!
        state_res = await client.get("/api/v1/onboarding/platforms", headers=headers)
        state_data = state_res.json()
        assert "amazon" in state_data["platform_urls"]
        assert "flipkart" in state_data["platform_urls"]
        assert state_data["platform_analysis_status"]["flipkart"] in ["pending", "completed"]


# -----------------------------------------------------------------------------
# 3. No Online Presence Brand Kit reuse without failing on optional fields
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_online_presence_brand_kit_reuse(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Select No Online Presence
        await client.post("/api/v1/onboarding/online-presence", headers=headers, json={"online_presence": "no_online_presence"})

        # 2. Save Brand Kit with missing optional fields (no logo, no tones, no palette)
        brand_payload = {
            "business_name": "Artisan Candles India",
            "tagline": "Handcrafted with pure love",
            "category": "Home Decor"
        }
        res = await client.post("/api/v1/brands", headers=headers, json=brand_payload)
        assert res.status_code in [200, 201]
        data = res.json()
        assert data["data"]["business_name"] == "Artisan Candles India"

        # 3. Retrieve Brand Kit status
        status_res = await client.get("/api/v1/brands/onboarding-status", headers=headers)
        assert status_res.status_code == 200
        st_data = status_res.json()
        assert st_data.get("brand_kit", {}).get("business_name") == "Artisan Candles India"
        assert st_data["completion_percentage"] > 0


# -----------------------------------------------------------------------------
# 4. Skipped social and plan screens do NOT grant paid plan or mark connected
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skipped_social_and_plan_authoritative_entitlements(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Skip social connectivity
        res1 = await client.patch("/api/v1/onboarding/progress", headers=headers, json={"social_connectivity_skipped": True})
        assert res1.status_code == 200

        # Skip plan selection
        res2 = await client.patch("/api/v1/onboarding/progress", headers=headers, json={"plan_selection_skipped": True})
        assert res2.status_code == 200

        # Verify onboarding status
        status_res = await client.get("/api/v1/onboarding/status", headers=headers)
        assert status_res.status_code == 200
        s_data = status_res.json()

        # Step 2: skipped, but NOT connected
        step2 = s_data["steps"]["step_2_social_connectivity"]
        assert step2["is_skipped"] is True
        assert step2["is_completed"] is False
        assert step2["connected_count"] == 0

        # Step 3: skipped, but NOT active paid plan
        step3 = s_data["steps"]["step_3_subscription_plan"]
        assert step3["is_skipped"] is True
        assert step3["is_completed"] is False

        # Plan status remains authoritative FREE
        assert s_data["subscription_status"] in ["free", "active"]
        assert s_data["selected_plan_id"] == "FREE"


# -----------------------------------------------------------------------------
# 5. First-Post Source Images Aggregation
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_post_source_images_aggregation(free_user):
    headers, uid = free_user
    db = get_database()

    # Seed business photos and Brand Kit photos
    await db["businesses"].update_one(
        {"owner_id": uid},
        {"$set": {
            "owner_id": uid,
            "business_name": "Royal Silks",
            "photos": ["https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b"],
            "scraped_images": ["https://images.unsplash.com/photo-1610030469983-98e550d6193c"],
            "online_presence": "website"
        }},
        upsert=True
    )
    await db["brand_kits"].update_one(
        {"owner_id": uid},
        {"$set": {
            "owner_id": uid,
            "logo_url": "https://cdn.example.com/logo.png",
            "selected_photos": ["https://images.unsplash.com/photo-1556228720-195a672e8a03"]
        }},
        upsert=True
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/onboarding/first-post/source-images", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["total_count"] >= 3

        urls = [img["url"] for img in data["images"]]
        assert "https://cdn.example.com/logo.png" in urls
        logo_item = next(img for img in data["images"] if img["url"] == "https://cdn.example.com/logo.png")
        assert logo_item["is_logo"] is True
        assert logo_item["source"] == "brand_kit"


# -----------------------------------------------------------------------------
# 6. Secure Image Upload for First-Post
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_post_image_upload(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a valid in-memory test image
        img = Image.new("RGB", (200, 200), color=(73, 109, 137))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        # Upload valid PNG
        files = {"file": ("test_product.png", img_bytes.getvalue(), "image/png")}
        res = await client.post("/api/v1/onboarding/first-post/upload-image", headers=headers, files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "image_url" in data
        assert data["content_type"] == "image/png"

        # Verify the photo was registered on the business record
        db = get_database()
        bus = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]})
        assert data["image_url"] in bus.get("photos", [])

        # Try uploading invalid text file as image
        bad_files = {"file": ("malicious.sh", b"echo 'hack'", "text/x-shellscript")}
        bad_res = await client.post("/api/v1/onboarding/first-post/upload-image", headers=headers, files=bad_files)
        assert bad_res.status_code == 400


# -----------------------------------------------------------------------------
# 7. First Content Choice Transition (Post Maker / Photoshoot / Reel Maker)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_content_choice_transition(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Post Maker
        res1 = await client.post("/api/v1/onboarding/first-content/choice", headers=headers, json={"content_choice": "post_maker"})
        assert res1.status_code == 200
        assert res1.json()["content_choice"] == "post_maker"
        assert res1.json()["route"] == "/onboarding/first-post"

        # 2. AI Photoshoot
        res2 = await client.post("/api/v1/onboarding/first-content/choice", headers=headers, json={"content_choice": "ai_photoshoot"})
        assert res2.status_code == 200
        assert res2.json()["content_choice"] == "ai_photoshoot"

        # 3. Reel Maker
        res3 = await client.post("/api/v1/onboarding/first-content/choice", headers=headers, json={"content_choice": "reel_maker"})
        assert res3.status_code == 200
        assert res3.json()["content_choice"] == "reel_maker"


# -----------------------------------------------------------------------------
# 8. Idempotency & Duplicate Prevention
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_first_post_generation(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        req_payload = {
            "content_choice": "post_maker",
            "prompt": "Festive special launch of handcrafted soaps",
            "idempotency_key": f"idemp_{uid}_101"
        }

        # First request
        res1 = await client.post("/api/v1/onboarding/first-post/generate", headers=headers, json=req_payload)
        assert res1.status_code == 200
        job1 = res1.json()
        assert job1["success"] is True
        job_id_1 = job1["job_id"]

        # Duplicate click with same idempotency key
        res2 = await client.post("/api/v1/onboarding/first-post/generate", headers=headers, json=req_payload)
        assert res2.status_code == 200
        job2 = res2.json()
        assert job2["job_id"] == job_id_1, "Repeated click must return the existing generation job"

        # Polling status endpoint
        poll_res = await client.get(f"/api/v1/onboarding/first-post/status/{job_id_1}", headers=headers)
        assert poll_res.status_code == 200
        assert poll_res.json()["job_id"] == job_id_1


# -----------------------------------------------------------------------------
# 9. Three-Preview Result & Access Control (Free Plan: 1 Unlocked + 2 Locked)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_previews_access_control_free_plan(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "content_choice": "post_maker",
            "prompt": "Diwali special handcrafted candle gift box",
            "idempotency_key": f"free_gen_{uid}"
        }
        res = await client.post("/api/v1/onboarding/first-post/generate", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert len(data["previews"]) == 3

        # Preview 1: UNLOCKED
        prev1 = data["previews"][0]
        assert prev1["is_locked"] is False
        assert prev1["lock_reason"] is None
        assert prev1["content_id"] is not None
        assert len(prev1["caption"]) > 10
        assert data["unlocked_content_id"] == prev1["content_id"]

        # Previews 2 & 3: LOCKED behind paid plan
        for idx in [1, 2]:
            prev_locked = data["previews"][idx]
            assert prev_locked["is_locked"] is True
            assert prev_locked["lock_reason"] == "upgrade_required"
            assert prev_locked["upgrade_required"] is True
            assert prev_locked["content_id"] is None
            assert "Upgrade" in prev_locked["caption"]


# -----------------------------------------------------------------------------
# 10. Three-Preview Result & Access Control (Paid Plan: All 3 Unlocked)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_previews_access_control_paid_plan(paid_user):
    headers, uid = paid_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "content_choice": "post_maker",
            "prompt": "Summer collection luxury sunglasses",
            "idempotency_key": f"paid_gen_{uid}"
        }
        res = await client.post("/api/v1/onboarding/first-post/generate", headers=headers, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert len(data["previews"]) == 3

        # On active Starter/Paid plan, all 3 previews are unlocked with real copy and saved IDs
        for idx in range(3):
            prev = data["previews"][idx]
            assert prev["is_locked"] is False
            assert prev["lock_reason"] is None
            assert prev["content_id"] is not None
            assert "Upgrade" not in prev["caption"]


# -----------------------------------------------------------------------------
# 11. Create Post Dashboard Editor Retrieval Compatibility
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlocked_preview_retrieval_in_create_post_dashboard(free_user):
    headers, uid = free_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Generate post
        res = await client.post(
            "/api/v1/onboarding/first-post/generate",
            headers=headers,
            json={"prompt": "Grand opening promotional announcement", "idempotency_key": f"dash_{uid}"}
        )
        assert res.status_code == 200
        unlocked_content_id = res.json()["unlocked_content_id"]
        assert unlocked_content_id is not None

        # Fetch directly via Create Post dashboard route: GET /api/v1/content/{content_id}
        dash_res = await client.get(f"/api/v1/content/{unlocked_content_id}", headers=headers)
        assert dash_res.status_code == 200, f"Dashboard retrieval failed: {dash_res.text}"
        dash_data = dash_res.json()["data"]
        assert dash_data["_id"] == unlocked_content_id
        assert dash_data["status"] == "draft"
        assert "caption" in dash_data
        assert "hashtags" in dash_data

        # Update in dashboard editor mode: PUT /api/v1/content/update
        edit_payload = {
            "_id": unlocked_content_id,
            "caption": "Updated caption from the Create Post editor!"
        }
        update_res = await client.put("/api/v1/content/update", headers=headers, json=edit_payload)
        assert update_res.status_code == 200
        assert update_res.json()["data"]["caption"] == "Updated caption from the Create Post editor!"


# -----------------------------------------------------------------------------
# 12. Ownership and Security Checks
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_and_content_ownership_security(free_user, other_user):
    user_a_headers, user_a_id = free_user
    intruder_headers, intruder_id = other_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A generates a post
        res = await client.post(
            "/api/v1/onboarding/first-post/generate",
            headers=user_a_headers,
            json={"prompt": "Confidential internal product launch"}
        )
        job_data = res.json()
        job_id = job_data["job_id"]
        content_id = job_data["unlocked_content_id"]

        # Intruder attempts to poll User A's job status -> 403 Forbidden
        status_res = await client.get(f"/api/v1/onboarding/first-post/status/{job_id}", headers=intruder_headers)
        assert status_res.status_code == 403

        # Intruder attempts to read User A's post in dashboard editor -> 404 Not Found (scoped by business)
        content_res = await client.get(f"/api/v1/content/{content_id}", headers=intruder_headers)
        assert content_res.status_code == 404
