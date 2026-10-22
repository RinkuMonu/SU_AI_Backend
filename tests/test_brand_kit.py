import io
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.ai.image.generator import ImageGenerator

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


import uuid
import random

_phone_counter = 0

async def create_user_with_token(db, role: str = "businessman", name: str = "Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    # Guaranteed unique 10-digit number starting with 9
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


# --------------------------------------------------------------------------
# 1. New Businessman Onboarding State
# --------------------------------------------------------------------------
async def test_new_businessman_onboarding_state():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="New Biz User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Check /onboarding-status
        res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "businessman"
        assert data["should_show_modal"] is True
        assert data["brand_kit_status"] == "not_started"
        assert data["brand_kit_completed"] is False
        assert data["brand_kit"] is None

        # Check /status alias
        res_alias = await ac.get("/api/v1/brands/status", headers=headers)
        assert res_alias.status_code == 200
        assert res_alias.json()["should_show_modal"] is True
        assert res_alias.json()["brand_kit_status"] == "not_started"


# --------------------------------------------------------------------------
# 2. Draft Save and Retrieval
# --------------------------------------------------------------------------
async def test_draft_save_and_retrieval():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Draft User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        draft_payload = {
            "business_name": "Apex Innovations",
            "business_type": "Private Limited",
            "primary_color": "#1E40AF",
            "tagline": "Innovate the future"
        }

        # Save draft
        res = await ac.post("/api/v1/brands/draft", json=draft_payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["brand_kit_status"] == "in_progress"
        assert data["brand_kit_completed"] is False
        assert data["data"]["business_name"] == "Apex Innovations"
        assert data["data"]["primary_color"] == "#1E40AF"

        # Onboarding status must reflect in_progress and modal must still show
        status_res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["should_show_modal"] is True
        assert status_data["brand_kit_status"] == "in_progress"
        assert status_data["brand_kit_completed"] is False
        assert status_data["brand_kit"]["business_name"] == "Apex Innovations"

        # Sidebar retrieval /brands
        get_res = await ac.get("/api/v1/brands", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["data"]["business_name"] == "Apex Innovations"


# --------------------------------------------------------------------------
# 3. Brand Kit Completion Success
# --------------------------------------------------------------------------
async def test_brand_kit_completion_success():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Complete User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        full_payload = {
            "business_name": "Zenith AI Corp",
            "business_type": "Private Limited",
            "registration_number": "REG-2026-9988",
            "business_model": "B2B",
            "selling_model": "SaaS Subscription",
            "business_category": "Software & AI",
            "business_description": "We build next-generation enterprise marketing and automation tools.",
            "logo_url": "/uploads/brand/zenith_logo.png",
            "primary_color": "#7C3AED",
            "secondary_color": "#F97316",
            "accent_color": "#10B981",
            "font": "Inter",
            "age_group": "25-35",
            "gender": "All",
            "customer_type": "Tech Entrepreneurs",
            "location_focus": "Bangalore, Karnataka",
            "generating_for": ["LinkedIn Post", "Instagram Post", "Reels & Stories"]
        }

        # Complete Brand Kit
        res = await ac.post("/api/v1/brands/complete", json=full_payload, headers=headers)
        assert res.status_code == 200
        res_data = res.json()
        assert res_data["success"] is True
        assert res_data["brand_kit_status"] == "completed"
        assert res_data["brand_kit_completed"] is True
        assert res_data["data"]["brand_kit_completed_at"] is not None

        # Onboarding status: modal should NO LONGER show
        status_res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["should_show_modal"] is False
        assert status_data["brand_kit_status"] == "completed"
        assert status_data["brand_kit_completed"] is True

        # Sidebar access remains available
        sidebar_res = await ac.get("/api/v1/brands", headers=headers)
        assert sidebar_res.status_code == 200
        assert sidebar_res.json()["data"]["business_name"] == "Zenith AI Corp"
        assert sidebar_res.json()["data"]["brand_kit_completed"] is True


# --------------------------------------------------------------------------
# 4. Field-Level Validation Failure on Missing Required Fields
# --------------------------------------------------------------------------
async def test_validation_failure_missing_required_fields():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Validation User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Incomplete payload: missing logo, colors, font, audience, description
        incomplete_payload = {
            "business_name": "Incomplete Enterprise",
            "business_type": "Partnership"
        }

        res = await ac.post("/api/v1/brands/complete", json=incomplete_payload, headers=headers)
        assert res.status_code == 422
        data = res.json()
        assert "detail" in data
        missing_fields = data["detail"].get("missing_fields", {})
        assert "business_model" in missing_fields
        assert "selling_model" in missing_fields
        assert "business_category" in missing_fields
        assert "business_description" in missing_fields
        assert "logo_url" in missing_fields
        assert "primary_color" in missing_fields
        assert "font" in missing_fields
        assert "age_group" in missing_fields
        # registration_number is NOT required and must not be in missing_fields
        assert "registration_number" not in missing_fields

        # Status must not be marked complete
        status_res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert status_res.json()["brand_kit_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 5. Invalid Color Validation (Hex Colors Only, No Arbitrary CSS)
# --------------------------------------------------------------------------
async def test_color_validation_invalid_hex():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Color User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Test arbitrary CSS color strings or invalid hex
        invalid_colors = ["red", "rgb(255,0,0)", "hsl(120, 100%, 50%)", "#GGGGGG", "#12", "#123456789"]
        for bad_color in invalid_colors:
            res = await ac.post("/api/v1/brands/draft", json={
                "business_name": "Color Test",
                "primary_color": bad_color
            }, headers=headers)
            assert res.status_code == 422, f"Expected 422 for invalid color: {bad_color}"


# --------------------------------------------------------------------------
# 6. Valid Custom Color Normalization
# --------------------------------------------------------------------------
async def test_color_normalization():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Norm Color User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Test lowercase 6-digit hex and 3-digit hex without # prefix or with #
        res = await ac.post("/api/v1/brands/draft", json={
            "business_name": "Norm Colors",
            "primary_color": "7c3aed",      # without hash
            "secondary_color": "#f97316",    # lowercase
            "accent_color": "#f0a"           # 3-digit hex
        }, headers=headers)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["primary_color"] == "#7C3AED"
        assert data["secondary_color"] == "#F97316"
        assert data["accent_color"] == "#FF00AA"


# --------------------------------------------------------------------------
# 7. Optional Structured Gradient Validation
# --------------------------------------------------------------------------
async def test_gradient_validation():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Gradient User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Valid linear gradient
        valid_gradient = {
            "business_name": "Gradient Biz",
            "gradient": {
                "gradient_type": "linear",
                "angle": 135.0,
                "stops": [
                    {"color": "#7C3AED", "position": 0.0},
                    {"color": "#F97316", "position": 100.0}
                ]
            }
        }
        res = await ac.post("/api/v1/brands/draft", json=valid_gradient, headers=headers)
        assert res.status_code == 200
        grad = res.json()["data"]["gradient"]
        assert grad["gradient_type"] == "linear"
        assert grad["angle"] == 135.0
        assert len(grad["stops"]) == 2
        assert grad["stops"][0]["color"] == "#7C3AED"

        # Invalid gradient type (e.g. "conic")
        invalid_grad = {
            "business_name": "Invalid Grad",
            "gradient": {
                "gradient_type": "conic",
                "angle": 90.0,
                "stops": []
            }
        }
        res_inv = await ac.post("/api/v1/brands/draft", json=invalid_grad, headers=headers)
        assert res_inv.status_code == 422

        # Invalid stop color in gradient
        invalid_stop_grad = {
            "business_name": "Invalid Stop Grad",
            "gradient": {
                "gradient_type": "linear",
                "angle": 90.0,
                "stops": [
                    {"color": "not-a-color", "position": 0.0}
                ]
            }
        }
        res_inv_stop = await ac.post("/api/v1/brands/draft", json=invalid_stop_grad, headers=headers)
        assert res_inv_stop.status_code == 422


# --------------------------------------------------------------------------
# 8. Logo Upload Validation (Allowed vs Disallowed)
# --------------------------------------------------------------------------
async def test_logo_upload_validation():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Upload User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Valid PNG upload
        fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        files = {"file": ("test_logo.png", io.BytesIO(fake_png_data), "image/png")}
        res = await ac.post("/api/v1/brands/upload-logo", files=files, headers=headers)
        assert res.status_code == 200
        upload_data = res.json()
        assert upload_data["success"] is True
        assert "/uploads/brand/" in upload_data["data"]["logo_url"]

        # 2. Invalid file type upload (.txt)
        bad_files = {"file": ("bad_script.txt", io.BytesIO(b"malicious script"), "text/plain")}
        res_bad = await ac.post("/api/v1/brands/upload-logo", files=bad_files, headers=headers)
        assert res_bad.status_code == 400
        assert "Invalid file format" in res_bad.json()["detail"]


# --------------------------------------------------------------------------
# 9. AI Logo Generation Integration (Mocked Image Generator)
# --------------------------------------------------------------------------
async def test_ai_logo_generation_flow():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="AI Logo User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Mock ImageGenerator.generate_image to avoid external API calls
        mock_ai_result = {
            "image_url": "https://fake-ai-cdn.com/generated_emblem.png",
            "prompt": "vector emblem logo for Quantum Flow Tech",
            "model": "imagen-3"
        }

        fake_image_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"

        with patch.object(ImageGenerator, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_ai_result
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.content = fake_image_bytes
                mock_get.return_value = mock_resp

                res = await ac.post("/api/v1/brands/generate-logo", json={
                    "business_name": "Quantum Flow Tech",
                    "business_category": "AI Automation",
                    "style": "modern luxury minimalist vector emblem",
                    "preferred_colors": ["#7C3AED", "#F97316"]
                }, headers=headers)

                assert res.status_code == 200
                res_data = res.json()
                assert res_data["success"] is True
                assert "/uploads/brand/" in res_data["data"]["logo_url"]
                assert res_data["data"]["business_name"] == "Quantum Flow Tech"


# --------------------------------------------------------------------------
# 10. Duplicate Submissions Are Idempotent (No Duplicate MongoDB Documents)
# --------------------------------------------------------------------------
async def test_duplicate_submissions_idempotency():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Idempotent User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Submit draft twice
        draft_1 = {"business_name": "Idempotent Corp v1", "primary_color": "#111111"}
        draft_2 = {"business_name": "Idempotent Corp v2", "primary_color": "#222222"}

        res1 = await ac.post("/api/v1/brands/draft", json=draft_1, headers=headers)
        assert res1.status_code == 200

        res2 = await ac.post("/api/v1/brands/draft", json=draft_2, headers=headers)
        assert res2.status_code == 200

        # Assert only 1 brand kit exists for this owner
        brand_count = await db["brand_kits"].count_documents({"owner_id": user_id})
        assert brand_count == 1

        brand_doc = await db["brand_kits"].find_one({"owner_id": user_id})
        assert brand_doc["business_name"] == "Idempotent Corp v2"
        assert brand_doc["primary_color"] == "#222222"


# --------------------------------------------------------------------------
# 11. Unauthorized Access Checks
# --------------------------------------------------------------------------
async def test_unauthorized_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Invalid / expired token
        invalid_headers = {"Authorization": "Bearer invalid.expired.token"}
        res = await ac.get("/api/v1/brands/onboarding-status", headers=invalid_headers)
        assert res.status_code == 401

        res_draft = await ac.post("/api/v1/brands/draft", json={"business_name": "Hack"}, headers=invalid_headers)
        assert res_draft.status_code == 401


# --------------------------------------------------------------------------
# 12. Cross-User Data Isolation
# --------------------------------------------------------------------------
async def test_cross_user_isolation():
    db = get_database()
    user_a, token_a, _ = await create_user_with_token(db, role="businessman", name="User Alpha")
    user_b, token_b, _ = await create_user_with_token(db, role="businessman", name="User Beta")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A saves draft A
        await ac.post("/api/v1/brands/draft", json={"business_name": "Alpha Corp"}, headers=headers_a)

        # User B saves draft B
        await ac.post("/api/v1/brands/draft", json={"business_name": "Beta LLC"}, headers=headers_b)

        # User A reads their brand
        res_a = await ac.get("/api/v1/brands", headers=headers_a)
        assert res_a.json()["data"]["business_name"] == "Alpha Corp"

        # User B reads their brand
        res_b = await ac.get("/api/v1/brands", headers=headers_b)
        assert res_b.json()["data"]["business_name"] == "Beta LLC"

        # Ensure no cross-contamination
        assert res_a.json()["data"]["business_name"] != res_b.json()["data"]["business_name"]


# --------------------------------------------------------------------------
# 13. Persistence Across Sessions / Relogin
# --------------------------------------------------------------------------
async def test_persistence_across_sessions():
    db = get_database()
    user_id, token_1, _ = await create_user_with_token(db, role="businessman", name="Session User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Session 1: Save draft
        headers_1 = {"Authorization": f"Bearer {token_1}"}
        await ac.post("/api/v1/brands/draft", json={"business_name": "Persistent Brands"}, headers=headers_1)

        # Simulate logout and new login (new token)
        token_2 = create_access_token(subject=user_id)
        headers_2 = {"Authorization": f"Bearer {token_2}"}

        # In session 2, onboarding status must be preserved
        res = await ac.get("/api/v1/brands/onboarding-status", headers=headers_2)
        assert res.status_code == 200
        assert res.json()["brand_kit_status"] == "in_progress"
        assert res.json()["should_show_modal"] is True
        assert res.json()["brand_kit"]["business_name"] == "Persistent Brands"


# --------------------------------------------------------------------------
# 14. Existing / Legacy Brand Kit Records Handling
# --------------------------------------------------------------------------
async def test_legacy_brand_kit_record_handling():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman", name="Legacy User")

    # Manually insert legacy brand kit without new status fields
    legacy_brand_id = ObjectId()
    business_id = ObjectId()

    await db["businesses"].insert_one({
        "_id": business_id,
        "owner_id": user_id,
        "name": "Legacy Enterprise"
    })

    await db["brand_kits"].insert_one({
        "_id": legacy_brand_id,
        "business_id": ObjectId(business_id),
        "owner_id": user_id,
        "business_name": "Legacy Enterprise",
        "brand_name": "Legacy Enterprise",
        "business_type": "Private Limited",
        "business_model": "B2B",
        "selling_model": "Direct",
        "business_category": "Industrial",
        "business_description": "Legacy established manufacturing entity.",
        "logo_url": "/uploads/brand/legacy.png",
        "primary_color": "#112233",
        "secondary_color": "#445566",
        "accent_color": "#778899",
        "font": "Roboto",
        "age_group": "35-50",
        "customer_type": "Enterprises",
        "location_focus": "Delhi, India"
        # Notice: brand_kit_status, brand_kit_completed, brand_kit_completed_at are missing
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Calling onboarding-status should detect complete legacy data and recognize it as completed
        res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["should_show_modal"] is False
        assert data["brand_kit_status"] == "completed"
        assert data["brand_kit_completed"] is True


# --------------------------------------------------------------------------
# 15. Businessman vs Influencer Role Behavior
# --------------------------------------------------------------------------
async def test_businessman_vs_influencer_behavior():
    db = get_database()
    inf_id, inf_token, _ = await create_user_with_token(db, role="influencer", name="Influencer Star")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {inf_token}"}

        # 1. Influencer querying onboarding-status
        res = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "influencer"
        # Influencer modal MUST NOT show
        assert data["should_show_modal"] is False
        assert data["brand_kit_status"] == "not_applicable"
        assert data["brand_kit_completed"] is True

        # 2. Influencer attempting to save brand kit draft -> 403 Forbidden
        draft_res = await ac.post("/api/v1/brands/draft", json={"business_name": "Influencer Biz"}, headers=headers)
        assert draft_res.status_code == 403
        assert "Businessman role required" in draft_res.json()["detail"]

        # 3. Influencer attempting to complete brand kit -> 403 Forbidden
        comp_res = await ac.post("/api/v1/brands/complete", json={"business_name": "Influencer Biz"}, headers=headers)
        assert comp_res.status_code == 403
