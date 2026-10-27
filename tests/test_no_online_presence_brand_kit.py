import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token, get_password_hash
from app.ai.services.business_context import BusinessContextService


@pytest.fixture(autouse=True)
def ensure_db():
    connect_to_mongo()


@pytest.fixture
async def auth_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "No Online Presence Tester 1",
        "email": f"nopresence_{str(uid)[-6:]}@test.com",
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
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, str(uid)


@pytest.fixture
async def auth_user2():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "No Online Presence Tester 2",
        "email": f"nopresence2_{str(uid)[-6:]}@test.com",
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
    token = create_access_token(subject=str(uid))
    return {"Authorization": f"Bearer {token}"}, str(uid)


# -----------------------------------------------------------------------------
# 1. No Online Presence Selection & Persistence
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_online_presence_selection_and_persistence(auth_user):
    headers, uid = auth_user
    db = get_database()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/onboarding/online-presence",
            json={
                "online_presence": "no_online_presence"
            },
            headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["online_presence"] == "no_online_presence"
        assert body["onboarding_step"] == 2
        assert body["onboarding_status"] == "in_progress"
        assert body["next_step"] == "brand_kit"
        assert body["can_access_dashboard"] is False

    # Verify database persistence
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user_doc["online_presence"] == "no_online_presence"
    assert user_doc["onboarding_step"] == 2

    biz_doc = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]})
    assert biz_doc is not None
    assert biz_doc["online_presence"] == "no_online_presence"


# -----------------------------------------------------------------------------
# 2. Brand Kit Status for New No Online Presence User
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initial_brand_kit_status_for_no_online_presence(auth_user):
    headers, uid = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Select no online presence
        await ac.post(
            "/api/v1/onboarding/online-presence",
            json={"online_presence": "no_online_presence"},
            headers=headers
        )

        # 2. Check initial brand onboarding status
        resp = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "businessman"
        assert data["should_show_modal"] is True
        assert data["brand_kit_status"] == "not_started"
        assert data["brand_kit_completed"] is False
        assert data["completion_percentage"] == 0
        assert len(data["completed_sections"]) == 0
        assert "business_identity" in data["pending_sections"]

        # 3. Fetch initial brand kit
        get_resp = await ac.get("/api/v1/brands", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["data"] is None


# -----------------------------------------------------------------------------
# 3. Partial Save Support Without Required Fields
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_brand_kit_save_without_required_fields(auth_user):
    headers, uid = auth_user
    db = get_database()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Select no online presence first
        await ac.post(
            "/api/v1/onboarding/online-presence",
            json={"online_presence": "no_online_presence"},
            headers=headers
        )

        # Partial save: only primary_color and font (business_name, logo, etc. are omitted!)
        resp = await ac.post(
            "/api/v1/brands",
            json={
                "primary_color": "#2563EB",
                "font": "Inter"
            },
            headers=headers
        )
        assert resp.status_code == 201
        res = resp.json()
        assert res["success"] is True
        assert res["brand_kit_status"] == "in_progress"
        assert res["brand_kit_completed"] is False
        assert res["completion_percentage"] > 0
        assert res["completion_percentage"] < 100
        assert res["data"]["primary_color"] == "#2563EB"
        assert res["data"]["font"] == "Inter"

    # Verify database persistence
    bk = await db["brand_kits"].find_one({"owner_id": uid})
    assert bk is not None
    assert bk["primary_color"] == "#2563EB"
    assert bk["font"] == "Inter"
    assert bk["brand_kit_status"] == "in_progress"
    assert bk["brand_kit_completed"] is False
    assert bk.get("online_presence") == "no_online_presence"


# -----------------------------------------------------------------------------
# 4. Partial Updates Preserve Omitted Fields
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_updating_selected_fields_preserves_omitted_values(auth_user):
    headers, uid = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Setup initial partial save
        await ac.post(
            "/api/v1/brands",
            json={
                "business_name": "Apex Footwear",
                "primary_color": "#1E40AF",
                "font": "Roboto"
            },
            headers=headers
        )

        # Update ONLY secondary_color and business_category; primary_color, font, and business_name are omitted!
        update_resp = await ac.put(
            "/api/v1/brands",
            json={
                "secondary_color": "#10B981",
                "business_category": "Footwear & Retail"
            },
            headers=headers
        )
        assert update_resp.status_code == 200
        data = update_resp.json()["data"]

        # Verify new fields were applied
        assert data["secondary_color"] == "#10B981"
        assert data["business_category"] == "Footwear & Retail"

        # Verify omitted fields were NOT lost
        assert data["primary_color"] == "#1E40AF"
        assert data["font"] == "Roboto"
        assert data["business_name"] == "Apex Footwear"


# -----------------------------------------------------------------------------
# 5. Distinguish Omitted vs Explicitly Cleared Fields
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_distinguish_omitted_vs_explicitly_cleared_fields(auth_user):
    headers, uid = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Save initial brand kit with tagline and secondary_color
        await ac.post(
            "/api/v1/brands",
            json={
                "business_name": "Apex Footwear",
                "tagline": "Step Into Luxury",
                "primary_color": "#1E40AF",
                "secondary_color": "#10B981"
            },
            headers=headers
        )

        # Explicitly clear 'tagline' and 'secondary_color' using clear_fields
        clear_resp = await ac.put(
            "/api/v1/brands",
            json={
                "clear_fields": ["tagline", "secondary_color"],
                "accent_color": "#F59E0B"
            },
            headers=headers
        )
        assert clear_resp.status_code == 200
        cleared_data = clear_resp.json()["data"]

        # Tagline and secondary_color should be cleared
        assert cleared_data.get("tagline") is None
        assert cleared_data.get("secondary_color") is None

        # Primary color and business name were omitted from update, so they must be preserved!
        assert cleared_data["primary_color"] == "#1E40AF"
        assert cleared_data["business_name"] == "Apex Footwear"
        assert cleared_data["accent_color"] == "#F59E0B"


# -----------------------------------------------------------------------------
# 6. Preserving All Extended Brand Kit Capabilities
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persisting_all_brand_kit_capabilities(auth_user):
    headers, uid = auth_user

    payload = {
        "business_name": "Heritage Fabrics",
        "business_type": "Retail & E-commerce",
        "business_category": "Textiles",
        "sub_category": "Ethnic Wear",
        "primary_color": "#7C3AED",
        "secondary_color": "#EC4899",
        "brand_colors": ["#7C3AED", "#EC4899", "#F43F5E"],
        "palette": ["#7C3AED", "#EC4899"],
        "font": "Poppins",
        "brand_voice": "Elegant, authentic, handcrafted",
        "tones": ["Artisanal", "Prestigious"],
        "differentiators": ["Handloom verified", "100% natural dyes"],
        "products_services": ["Silk Sarees", "Linen Kurtas"],
        "selected_photos": ["https://example.com/photos/saree1.jpg"],
        "customer_type": "Discerning shoppers seeking authentic craftsmanship",
        "age_group": "25-50",
        "location_focus": "Pan-India"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        save_resp = await ac.post("/api/v1/brands", json=payload, headers=headers)
        assert save_resp.status_code == 201

        # Retrieve and verify all capabilities persisted
        get_resp = await ac.get("/api/v1/brands", headers=headers)
        assert get_resp.status_code == 200
        brand = get_resp.json()["data"]

        assert brand["business_name"] == "Heritage Fabrics"
        assert brand["sub_category"] == "Ethnic Wear"
        assert brand["primary_color"] == "#7C3AED"
        assert brand["secondary_color"] == "#EC4899"
        assert "#7C3AED" in brand["brand_colors"]
        assert "Artisanal" in brand["tones"]
        assert "Handloom verified" in brand["differentiators"]
        assert "Silk Sarees" in brand["products_services"]
        assert "https://example.com/photos/saree1.jpg" in brand["selected_photos"]


# -----------------------------------------------------------------------------
# 7. Resuming Incomplete Brand Kit After Refresh
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resuming_incomplete_brand_kit_after_refresh(auth_user):
    headers, uid = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Step 1: Onboarding source
        await ac.post(
            "/api/v1/onboarding/online-presence",
            json={"online_presence": "no_online_presence"},
            headers=headers
        )

        # Step 2: Save partial brand kit
        await ac.post(
            "/api/v1/brands",
            json={
                "business_name": "Urban Cafe",
                "primary_color": "#D97706"
            },
            headers=headers
        )

        # Simulate user closing app and reopening / refreshing
        status_resp = await ac.get("/api/v1/onboarding/status", headers=headers)
        assert status_resp.status_code == 200
        ob_status = status_resp.json()
        assert ob_status["online_presence"] == "no_online_presence"
        assert ob_status["onboarding_step"] == 2
        assert ob_status["next_step"] == "brand_kit"

        brand_status_resp = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert brand_status_resp.status_code == 200
        bs = brand_status_resp.json()
        assert bs["brand_kit_status"] == "in_progress"
        assert bs["brand_kit_completed"] is False
        assert bs["brand_kit"]["business_name"] == "Urban Cafe"
        assert bs["brand_kit"]["primary_color"] == "#D97706"


# -----------------------------------------------------------------------------
# 8. Dismiss & Skip Modal Behavior
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dismiss_and_skip_brand_kit_modal(auth_user):
    headers, uid = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        dismiss_resp = await ac.post("/api/v1/brands/dismiss", headers=headers)
        assert dismiss_resp.status_code == 200
        assert dismiss_resp.json()["should_show_modal"] is False

        status_resp = await ac.get("/api/v1/brands/onboarding-status", headers=headers)
        assert status_resp.status_code == 200
        assert status_resp.json()["should_show_modal"] is False
        assert status_resp.json()["brand_kit_completed"] is False


# -----------------------------------------------------------------------------
# 9. Complete Validation Requires Mandatory Fields
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_validation_requires_all_mandatory_fields(auth_user):
    headers, uid = auth_user
    db = get_database()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Attempt completion with incomplete payload (missing logo, audience, colors, etc.)
        resp = await ac.post(
            "/api/v1/brands/complete",
            json={
                "business_name": "Incomplete Business",
                "business_type": "Retail"
            },
            headers=headers
        )
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert "missing_fields" in body or "errors" in body

    # Verify not marked complete in DB
    bk = await db["brand_kits"].find_one({"owner_id": uid})
    if bk:
        assert bk.get("brand_kit_completed") is not True


# -----------------------------------------------------------------------------
# 10. Successful Full Brand Kit Completion
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_full_brand_kit_completion(auth_user):
    headers, uid = auth_user
    db = get_database()

    full_payload = {
        "business_name": "Zenith Cloud Solutions",
        "business_type": "B2B SaaS",
        "business_model": "Subscription",
        "selling_model": "Online Direct",
        "business_category": "Information Technology",
        "business_description": "Enterprise cloud security and observability platform for modern tech stacks.",
        "logo_url": "https://example.com/logo.png",
        "primary_color": "#0284C7",
        "secondary_color": "#38BDF8",
        "accent_color": "#F0F9FF",
        "font": "Inter",
        "brand_voice": "Authoritative, modern, tech-forward",
        "age_group": "25-54",
        "customer_type": "CTOs and engineering leaders",
        "location_focus": "Global"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/brands/complete", json=full_payload, headers=headers)
        assert resp.status_code == 200
        res = resp.json()
        assert res["success"] is True
        assert res["brand_kit_status"] == "completed"
        assert res["brand_kit_completed"] is True
        assert res["completion_percentage"] == 100

    # Verify DB update
    bk = await db["brand_kits"].find_one({"owner_id": uid})
    assert bk["brand_kit_status"] == "completed"
    assert bk["brand_kit_completed"] is True

    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user_doc.get("brand_kit_completed") is True


# -----------------------------------------------------------------------------
# 11. Downstream AI Integration with Incomplete & Complete Brand Kit
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_downstream_ai_integration_with_incomplete_brand_kit(auth_user):
    headers, uid = auth_user
    db = get_database()

    # Save only minimal brand kit (primary color and business name only, no logo, font, secondary color, etc.)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/api/v1/brands",
            json={
                "business_name": "Solo Artisan",
                "primary_color": "#B45309"
            },
            headers=headers
        )

    # Call BusinessContextService directly
    context = await BusinessContextService.get_business_context(
        business_id=uid,
        user_id=uid,
        db=db
    )
    assert context is not None
    assert "business" in context
    assert "brand" in context
    assert context["business"]["name"] == "Solo Artisan"
    assert context["brand"]["primary_color"] == "#B45309"

    # Missing optional fields must NOT fail or throw exceptions
    assert context["brand"]["secondary_color"] is None
    assert context["brand"]["font"] is None

    # Verify format_context_for_prompt produces clean markdown snippet without crashing
    prompt_str = BusinessContextService.format_context_for_prompt(context)
    assert isinstance(prompt_str, str)
    assert "Business: Solo Artisan" in prompt_str
    assert "Brand Primary Color: #B45309" in prompt_str


# -----------------------------------------------------------------------------
# 12. Correct Ownership, Authentication, and Isolation
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_user_isolation_and_auth(auth_user, auth_user2):
    headers1, uid1 = auth_user
    headers2, uid2 = auth_user2

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # User 1 saves their Brand Kit
        await ac.post(
            "/api/v1/brands",
            json={"business_name": "User 1 Brand", "primary_color": "#112233"},
            headers=headers1
        )

        # User 2 queries their own Brand Kit; must NOT see User 1's data
        u2_kit = await ac.get("/api/v1/brands", headers=headers2)
        assert u2_kit.status_code == 200
        assert u2_kit.json()["data"] is None

        # User 2 saves their own Brand Kit
        await ac.post(
            "/api/v1/brands",
            json={"business_name": "User 2 Brand", "primary_color": "#998877"},
            headers=headers2
        )

        # Verify User 1's Brand Kit was not altered
        u1_kit = await ac.get("/api/v1/brands", headers=headers1)
        assert u1_kit.status_code == 200
        assert u1_kit.json()["data"]["business_name"] == "User 1 Brand"
        assert u1_kit.json()["data"]["primary_color"] == "#112233"

        # Unauthenticated calls must return 401
        unauth_get = await ac.get("/api/v1/brands")
        assert unauth_get.status_code == 401

        unauth_post = await ac.post("/api/v1/brands", json={"primary_color": "#000000"})
        assert unauth_post.status_code == 401
