import os
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
from app.ai.prompts.post import build_post_prompt
from app.ai.prompts.reel import get_reel_script_prompt
from app.services.brand_service import resolve_user_brand_config, verify_logo_asset

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


_phone_counter = 0

async def create_user_with_token(db, role: str = "businessman", name: str = "Brand Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"brand_user_{uuid.uuid4().hex[:8]}@example.com"
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


async def setup_business_and_brand_kit(db, user_id: str, brand_name: str = "Apex Luxury", primary_color: str = "#1E3A8A", is_incomplete: bool = False):
    """Provisions a test business and Brand Kit in MongoDB."""
    biz_id = ObjectId()
    biz_doc = {
        "_id": biz_id,
        "owner_id": str(user_id),
        "name": brand_name,
        "category": "Fashion & Luxury",
        "industry": "Fashion",
        "description": "High-end artisanal luxury goods and fashion accessories.",
        "location": "Mumbai, India",
        "created_at": datetime.now(timezone.utc),
    }
    await db["businesses"].insert_one(biz_doc)

    brand_id = ObjectId()
    brand_doc = {
        "_id": brand_id,
        "business_id": biz_id,
        "owner_id": str(user_id),
        "business_name": "" if is_incomplete else brand_name,
        "brand_name": "" if is_incomplete else brand_name,
        "business_category": "Fashion & Luxury",
        "business_description": "High-end artisanal luxury goods and fashion accessories.",
        "primary_color": "" if is_incomplete else primary_color,
        "secondary_color": "#D97706",
        "accent_color": "#F59E0B",
        "font": "Playfair Display",
        "heading_font": "Playfair Display",
        "body_font": "Inter",
        "brand_voice": "Sophisticated, authoritative, prestigious",
        "tone": "Sophisticated",
        "tagline": "Timeless Elegance Redefined",
        "visual_style": "High-contrast luxury editorial aesthetic",
        "social_style": "High-contrast luxury editorial aesthetic",
        "target_audience": "Affluent professionals and luxury connoisseurs",
        "logo_url": "https://example.com/assets/apex_logo.png",
        "brand_kit_status": "not_started" if is_incomplete else "completed",
        "brand_kit_completed": not is_incomplete,
        "brand_kit_completed_at": None if is_incomplete else datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await db["brand_kits"].insert_one(brand_doc)
    return str(biz_id), str(brand_id), brand_doc


# ============================================================================
# 1. Unit Tests: Brand Guidelines in Prompt Builders
# ============================================================================

def test_build_post_prompt_brand_kit_on():
    """Unit Test: build_post_prompt must inject rich Brand Kit identity when use_brand_kit=True."""
    brand = {
        "brand_name": "Apex Footwear",
        "business_category": "Footwear",
        "primary_color": "#1E3A8A",
        "secondary_color": "#D97706",
        "accent_color": "#F59E0B",
        "brand_voice": "Bold, dynamic",
        "tagline": "Step into Greatness",
        "visual_style": "Urban athletic",
        "target_audience": "Athletes and sneaker enthusiasts"
    }
    prompt = build_post_prompt(
        business={"name": "Apex Footwear"},
        brand=brand,
        product={"name": "Apex Pro Runners"},
        platform="instagram",
        objective="product_promotion",
        language="English",
        use_brand_kit=True
    )

    assert "OFFICIAL BRAND KIT IDENTITY (USE_BRAND_KIT=TRUE)" in prompt
    assert "Apex Footwear" in prompt
    assert "#1E3A8A" in prompt
    assert "#D97706" in prompt
    assert "Bold, dynamic" in prompt
    assert "Step into Greatness" in prompt


def test_build_post_prompt_brand_kit_off():
    """Unit Test: build_post_prompt must NOT inject brand identity when use_brand_kit=False."""
    brand = {
        "brand_name": "Apex Footwear",
        "primary_color": "#1E3A8A",
        "brand_voice": "Bold, dynamic"
    }
    prompt = build_post_prompt(
        business={"name": "Apex Footwear"},
        brand=brand,
        product={"name": "Apex Pro Runners"},
        platform="instagram",
        objective="product_promotion",
        language="English",
        use_brand_kit=False
    )

    assert "OFFICIAL BRAND KIT IDENTITY" not in prompt
    assert "#1E3A8A" not in prompt


def test_reel_script_prompt_brand_kit_on():
    """Unit Test: get_reel_script_prompt must inject brand identity when use_brand_kit=True."""
    brand = {
        "brand_name": "Crown Jewels",
        "primary_color": "#FFD700",
        "secondary_color": "#1A1A1A",
        "brand_voice": "Prestigious and opulent",
        "visual_style": "Golden luxury shimmer",
        "tagline": "Crafted for Royalty"
    }
    prompt = get_reel_script_prompt(
        product={"name": "Diamond Solitaire Ring", "category": "Jewellery", "price": 49999},
        brand=brand,
        objective="sale",
        platform="instagram_reels",
        duration=15,
        language="English",
        tone="luxury",
        use_brand_kit=True
    )

    assert "BRAND IDENTITY GUIDELINES (BRAND KIT MODE: ON)" in prompt
    assert "Crown Jewels" in prompt
    assert "#FFD700" in prompt
    assert "Prestigious and opulent" in prompt
    assert "Crafted for Royalty" in prompt


def test_reel_script_prompt_brand_kit_off():
    """Unit Test: get_reel_script_prompt must NOT inject Brand Kit guidelines when use_brand_kit=False."""
    brand = {
        "brand_name": "Crown Jewels",
        "primary_color": "#FFD700",
    }
    prompt = get_reel_script_prompt(
        product={"name": "Diamond Solitaire Ring", "category": "Jewellery"},
        brand=brand,
        objective="sale",
        platform="instagram_reels",
        duration=15,
        language="English",
        tone="luxury",
        use_brand_kit=False
    )

    assert "BRAND IDENTITY GUIDELINES (BRAND KIT MODE: ON)" not in prompt


# ============================================================================
# 2. Integration Tests: AI Post Generation API
# ============================================================================

async def test_post_generation_with_brand_kit_on():
    """Integration Test: POST /api/v1/content/generate-post with use_brand_kit=True."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="Brand Post User")
    await setup_business_and_brand_kit(db, user_id, brand_name="Apex Luxury", primary_color="#1E3A8A")

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Experience Apex ✨", "caption": "Artisanal luxury designed for discerning tastes.", "call_to_action": "Shop the Collection", "hashtags": ["#luxury", "#apex"], "creative_direction": "Dramatic editorial lighting", "image_prompt": "Artisanal leather bag on marble pedestal"}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/generated_post.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "platform": "instagram",
                    "objective": "product_promotion",
                    "language": "English",
                    "additional_instruction": "Showcase our signature craftsmanship",
                    "use_brand_kit": True
                }
            )

        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["success"] is True
        post_data = data["data"]
        assert post_data["use_brand_kit"] is True
        assert post_data["brand_kit_applied"] is True
        assert post_data["brand_details"] is not None
        assert post_data["brand_details"]["brand_name"] == "Apex Luxury"
        assert post_data["brand_details"]["primary_color"] == "#1E3A8A"


async def test_post_generation_with_brand_kit_off():
    """Integration Test: POST /api/v1/content/generate-post with use_brand_kit=False."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="Manual Post User")
    await setup_business_and_brand_kit(db, user_id, brand_name="Apex Luxury", primary_color="#1E3A8A")

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Special Drop 🔥", "caption": "Clean post copy.", "call_to_action": "Buy Now", "hashtags": ["#trending"]}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/unbranded.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "platform": "instagram",
                    "objective": "product_promotion",
                    "language": "English",
                    "additional_instruction": "Casual weekend vibes",
                    "use_brand_kit": False
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["use_brand_kit"] is False
        assert data["brand_kit_applied"] is False
        assert data.get("brand_details") is None


async def test_post_generation_omitted_use_brand_kit_defaults_to_false():
    """Integration Test: Existing requests omitting use_brand_kit default to False (backward compatibility)."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Legacy Post", "caption": "Legacy test.", "call_to_action": "Click"}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/legacy.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "platform": "instagram",
                    "objective": "product_promotion",
                    "language": "English"
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["use_brand_kit"] is False
        assert data["brand_kit_applied"] is False


async def test_post_generation_missing_brand_kit_returns_400():
    """Integration Test: use_brand_kit=True with NO Brand Kit configured returns structured 400 error."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="No Brand User")
    # Do NOT setup brand kit

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "platform": "instagram",
                "objective": "product_promotion",
                "use_brand_kit": True
            }
        )

    assert res.status_code == 400
    err = res.json()
    detail = err.get("detail", {})
    assert detail.get("code") == "BRAND_KIT_MISSING" or "not configured" in str(detail).lower()


async def test_post_generation_incomplete_brand_kit_returns_400():
    """Integration Test: use_brand_kit=True with incomplete Brand Kit returns structured 400 error."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="Incomplete Brand User")
    await setup_business_and_brand_kit(db, user_id, is_incomplete=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "platform": "instagram",
                "objective": "product_promotion",
                "use_brand_kit": True
            }
        )

    assert res.status_code == 400
    err = res.json()
    detail = err.get("detail", {})
    assert detail.get("code") == "BRAND_KIT_INCOMPLETE" or "incomplete" in str(detail).lower()


# ============================================================================
# 3. Integration Tests: Reel Generation API
# ============================================================================

async def test_reel_generation_with_brand_kit_on():
    """Integration Test: POST /api/v1/content/generate-reel with use_brand_kit=True snapshots brand."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="Brand Reel User")
    await setup_business_and_brand_kit(db, user_id, brand_name="Velvet Couture", primary_color="#4C1D95")

    with patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock), \
         patch("app.services.subscription_service.SubscriptionService.increment_usage", new_callable=AsyncMock), \
         patch("app.services.reel_service.ReelService._process_reel_generation", new_callable=AsyncMock):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-reel",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Velvet Evening Gown",
                    "category": "Fashion & Apparel",
                    "product_description": "Hand-stitched silk velvet with delicate gold embroidery",
                    "duration": 15,
                    "use_brand_kit": True
                }
            )

        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["success"] is True
        job_id = data["job_id"]
        assert job_id is not None

        # Verify job doc in MongoDB has snapshotted Brand Kit configuration
        job_doc = await db["reel_jobs"].find_one({"_id": ObjectId(job_id)})
        assert job_doc is not None
        assert job_doc.get("use_brand_kit") is True
        assert job_doc.get("brand_kit_applied") is True
        assert job_doc.get("brand") is not None
        assert job_doc["brand"]["business_name"] == "Velvet Couture"
        assert job_doc["brand"]["primary_color"] == "#4C1D95"


async def test_reel_generation_with_brand_kit_off():
    """Integration Test: POST /api/v1/content/generate-reel with use_brand_kit=False."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="Manual Reel User")
    await setup_business_and_brand_kit(db, user_id, brand_name="Velvet Couture", primary_color="#4C1D95")

    with patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock), \
         patch("app.services.subscription_service.SubscriptionService.increment_usage", new_callable=AsyncMock), \
         patch("app.services.reel_service.ReelService._process_reel_generation", new_callable=AsyncMock):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-reel",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Velvet Evening Gown",
                    "category": "Fashion & Apparel",
                    "duration": 15,
                    "use_brand_kit": False
                }
            )

        assert res.status_code == 200
        job_id = res.json()["job_id"]
        job_doc = await db["reel_jobs"].find_one({"_id": ObjectId(job_id)})
        assert job_doc.get("use_brand_kit") is False
        assert job_doc.get("brand") is None


async def test_reel_generation_missing_brand_kit_returns_400():
    """Integration Test: POST /api/v1/content/generate-reel with use_brand_kit=True and NO Brand Kit."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, name="No Brand Reel User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-reel",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "product_name": "Generic Item",
                "use_brand_kit": True
            }
        )

    assert res.status_code == 400
    detail = res.json().get("detail", {})
    assert detail.get("code") == "BRAND_KIT_MISSING" or "not configured" in str(detail).lower()


# ============================================================================
# 4. Security & Isolation Tests
# ============================================================================

async def test_cross_user_brand_kit_isolation():
    """Security Test: User B cannot access User A's Brand Kit by any payload parameter."""
    db = get_database()
    user_a_id, token_a, _ = await create_user_with_token(db, name="User A")
    await setup_business_and_brand_kit(db, user_a_id, brand_name="Brand A Secret", primary_color="#111111")

    user_b_id, token_b, _ = await create_user_with_token(db, name="User B")
    # User B has NO Brand Kit configured

    # User B calls post generation with use_brand_kit=True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "platform": "instagram",
                "use_brand_kit": True,
                # Malicious payload attempt to inject User A's details
                "owner_id": user_a_id,
                "business_id": user_a_id
            }
        )

    # Must be 400 because Brand Kit resolution is strictly bound to current_user.id
    assert res.status_code == 400
    assert "not configured" in res.text.lower() or "BRAND_KIT_MISSING" in res.text


# ============================================================================
# 5. Asset Verification & Logo Handling
# ============================================================================

def test_verify_logo_asset_remote_url():
    """Test: verify_logo_asset validates remote HTTP/HTTPS URLs."""
    valid_url = "https://example.com/logo.png"
    assert verify_logo_asset(valid_url) == valid_url

    invalid_empty = ""
    assert verify_logo_asset(invalid_empty) is None

    none_url = None
    assert verify_logo_asset(none_url) is None


async def test_missing_logo_asset_graceful_handling():
    """Test: Brand Kit with missing/broken logo still resolves brand settings gracefully."""
    db = get_database()
    user_id, _, _ = await create_user_with_token(db)
    biz_id, _, brand_doc = await setup_business_and_brand_kit(db, user_id, brand_name="NoLogo Brand", primary_color="#2563EB")

    # Set non-existent local logo file
    await db["brand_kits"].update_one(
        {"_id": brand_doc["_id"]},
        {"$set": {"logo_url": "/uploads/brand/non_existent_logo_12345.png"}}
    )

    resolved = await resolve_user_brand_config(db, user_id=user_id, business_id=biz_id, require_usable=True)
    assert resolved is not None
    assert resolved["business_name"] == "NoLogo Brand"
    assert resolved["primary_color"] == "#2563EB"
    # Logo should be marked unavailable without crashing or fabricating fake URL
    assert resolved["logo_available"] is False
    assert resolved["logo_url"] is None
