import io
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

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


_phone_counter = 500

async def create_user_with_token(db, role: str = "businessman", name: str = "Product Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"prod_user_{uuid.uuid4().hex[:8]}@example.com"
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


async def insert_test_product(db, business_id: str, name: str = "Velvet Evening Gown", price: float = 4999.0):
    prod_id = ObjectId()
    prod_doc = {
        "_id": prod_id,
        "business_id": ObjectId(business_id),
        "name": name,
        "category": "Women Fashion",
        "description": "Handcrafted silk velvet evening gown with intricate golden zardozi embroidery.",
        "price": price,
        "sale_price": 3999.0,
        "features": [
            "Pure Mulberry Silk Velvet",
            "Hand-embroidered zardozi border",
            "Breathable viscose lining",
            "Custom fit tailoring"
        ],
        "sizes": ["S", "M", "L", "XL"],
        "colors": ["Royal Crimson", "Midnight Navy"],
        "stock": 25,
        "image_url": "https://example.com/products/gown1.jpg",
        "images": [
            "https://example.com/products/gown1.jpg",
            "https://example.com/products/gown2.jpg"
        ],
        "created_at": datetime.now(timezone.utc),
    }
    await db["products"].insert_one(prod_doc)
    return str(prod_id), prod_doc


# ============================================================================
# 1. FILE UPLOAD TESTS
# ============================================================================

async def test_upload_multiple_valid_product_images():
    """Uploads multiple valid product images and validates response structure and local file creation."""
    db = get_database()
    _, token, _ = await create_user_with_token(db)

    # 1KB dummy valid JPEG content
    fake_jpeg_1 = b"\xFF\xD8\xFF\xE0" + b"\x00" * 1200 + b"\xFF\xD9"
    fake_png_2 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1200 + b"\x00\x00\x00\x00IEND\xaeB`\x82"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        files = [
            ("files", ("product_front.jpg", io.BytesIO(fake_jpeg_1), "image/jpeg")),
            ("files", ("product_angle.png", io.BytesIO(fake_png_2), "image/png")),
        ]
        res = await ac.post(
            "/api/v1/content/upload-images",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 2
    assert len(data["data"]) == 2
    assert len(data["image_urls"]) == 2
    assert "uploads/products/" in data["image_urls"][0]
    assert "uploads/products/" in data["image_urls"][1]


async def test_upload_image_invalid_content_type():
    """Verifies that non-image uploads are strictly rejected with 400 Bad Request."""
    db = get_database()
    _, token, _ = await create_user_with_token(db)

    fake_exe = b"MZ" + b"\x00" * 1000

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        files = [
            ("files", ("malicious.exe", io.BytesIO(fake_exe), "application/x-msdownload")),
        ]
        res = await ac.post(
            "/api/v1/content/upload-images",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )

    assert res.status_code == 400
    assert "Invalid image format" in res.json()["detail"]


async def test_upload_image_exceeds_max_size():
    """Verifies that files larger than 15MB are rejected."""
    db = get_database()
    _, token, _ = await create_user_with_token(db)

    # 16 MB dummy content
    oversized = b"\xFF\xD8\xFF\xE0" + b"\x00" * (16 * 1024 * 1024)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        files = [
            ("files", ("giant.jpg", io.BytesIO(oversized), "image/jpeg")),
        ]
        res = await ac.post(
            "/api/v1/content/upload-images",
            headers={"Authorization": f"Bearer {token}"},
            files=files
        )

    assert res.status_code == 400
    assert "exceeds maximum allowed size" in res.json()["detail"]


async def test_upload_single_image_endpoint_backward_compatibility():
    """Verifies that the existing /upload-image endpoint works seamlessly."""
    db = get_database()
    _, token, _ = await create_user_with_token(db)

    fake_jpeg = b"\xFF\xD8\xFF\xE0" + b"\x00" * 1000 + b"\xFF\xD9"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/upload-image",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("single_product.jpg", io.BytesIO(fake_jpeg), "image/jpeg")}
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "uploads/products/" in data["image_url"]


# ============================================================================
# 2. PRODUCT-BASED POST GENERATION TESTS
# ============================================================================

async def test_product_post_generation_with_direct_details():
    """Generates social media post from direct product details (name, features, price, images)."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '''{
        "headline": "Step into Pure Comfort with AirFlex Pro 👟",
        "caption": "Engineered with breathable matrix mesh and responsive cloud foam cushioning. Only Rs. 2,999 today!",
        "call_to_action": "Order Your Pair Now | Free Shipping",
        "hashtags": ["#running", "#sneakers", "#AirFlexPro", "#fitness"],
        "creative_direction": "Studio sneaker hero shot with dynamic splash lighting",
        "image_prompt": "Studio product photograph of AirFlex Pro running shoes"
    }'''

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/generated/airflex.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "product_name": "AirFlex Pro Running Shoes",
                "product_description": "Ultra-lightweight marathon running shoes with responsive cushioning.",
                "price": 2999.0,
                "sale_price": 2499.0,
                "category": "Footwear",
                "features": [
                    "Responsive CloudFoam midsole",
                    "Breathable aerodynamic mesh upper",
                    "Anti-slip carbon rubber outsole"
                ],
                "product_images": [
                    "https://example.com/uploads/products/shoe_main.jpg",
                    "https://example.com/uploads/products/shoe_side.jpg"
                ],
                "platform": "instagram",
                "objective": "product_promotion",
                "content_type": "post",
                "use_brand_kit": False,
            }
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["content_type"] == "post"
        assert "AirFlex Pro" in data["headline"]
        assert "cloud foam" in data["caption"].lower() or "airflex" in data["caption"].lower()
        assert data["product_details"]["name"] == "AirFlex Pro Running Shoes"
        assert len(data["product_details"]["features"]) == 3
        assert data["image_url"] == "https://example.com/generated/airflex.jpg"

        # Verify saved in MongoDB contents collection
        saved = await db["contents"].find_one({"_id": ObjectId(data["_id"])})
        assert saved is not None
        assert saved["product_details"]["name"] == "AirFlex Pro Running Shoes"
        assert saved["type"] == "post"

        # Verify saved in ai_generations collection
        history_record = await db["ai_generations"].find_one({"user_id": str(user_id)})
        assert history_record is not None
        assert history_record["generation_type"] == "post"


async def test_product_post_generation_from_db_product():
    """Generates social media post by looking up an existing database product ID."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    biz_id, _, _ = await setup_business_and_brand_kit(db, user_id)
    prod_id, prod_doc = await insert_test_product(db, biz_id, name="Royal Crimson Velvet Lehenga", price=14999.0)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '''{
        "headline": "Embrace Royalty with Our Velvet Lehenga ✨",
        "caption": "Handcrafted silk velvet lehenga adorned with pure zardozi craftsmanship.",
        "call_to_action": "Shop the Festive Edition Now",
        "hashtags": ["#lehenga", "#velvet", "#festivelook"],
        "creative_direction": "Grand royal Indian palace setting",
        "image_prompt": "Photograph of Royal Crimson Velvet Lehenga"
    }'''

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/generated/lehenga.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_id": prod_id,
                    "platform": "instagram",
                    "objective": "product_promotion",
                    "use_brand_kit": False,
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["product_id"] == prod_id
        assert data["product_details"]["name"] == "Royal Crimson Velvet Lehenga"
        assert data["product_details"]["price"] == 14999.0
        assert "Lehenga" in data["headline"]


# ============================================================================
# 3. CONTENT TYPES TESTS (POST, CAPTION, AD, REEL)
# ============================================================================

async def test_product_caption_generation():
    """Tests dedicated caption generation, verifying caption copy and reuse of product image."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '''{
        "headline": "Upgrade Your Desk Setup 🖥️",
        "caption": "Precision machined aerospace aluminum stand with 360-degree rotation. Perfect ergonomic height for all-day focus. Price: ₹1,499.",
        "call_to_action": "Tap link in bio to order with 1-day delivery",
        "hashtags": ["#desksetup", "#workspace", "#productivity", "#aluminumstand"]
    }'''

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-caption",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "ErgoLift Aluminum Laptop Stand",
                    "product_description": "Ergonomic aluminum stand for MacBook and laptops.",
                    "price": 1499.0,
                    "features": ["Aerospace grade aluminum", "Dual hinge 360 rotation"],
                    "product_images": ["https://example.com/uploads/products/stand.jpg"],
                    "platform": "instagram",
                    "objective": "engagement",
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["content_type"] == "caption"
        assert "Desk Setup" in data["headline"]
        assert len(data["hashtags"]) >= 3
        # For captions, existing product image is reused as media_url
        assert data["media_url"] == "https://example.com/uploads/products/stand.jpg"


async def test_product_ad_generation():
    """Tests ad generation endpoint, verifying headline, primary_text, description, and cta."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '''{
        "headline": "Stop Hair Fall in 14 Days Guaranteed",
        "primary_text": "Clinically proven rosemary and redensyl serum that stimulates 10,000+ new hair strands. Over 50,000 satisfied customers.",
        "description": "50% OFF Festive Flash Sale. Limited stock available.",
        "call_to_action": "Shop Now - 50% Off",
        "hashtags": ["#haircare", "#hairgrowth", "#clinicallyproven"],
        "creative_direction": "Clean medical lab backdrop with golden serum dropper",
        "image_prompt": "Studio commercial ad of Hair Growth Serum"
    }'''

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/ads/serum_ad.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-ad",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "BioActive Hair Growth Serum",
                    "product_description": "Root stimulation serum with rosemary oil and redensyl.",
                    "price": 899.0,
                    "features": ["3% Redensyl", "Pure Spanish Rosemary", "Dermatologist Tested"],
                    "platform": "facebook",
                    "objective": "sales",
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["content_type"] == "ad"
        assert "Hair Fall" in data["headline"]
        assert data["primary_text"] is not None
        assert "rosemary" in data["primary_text"].lower()
        assert data["description"] is not None
        assert "Shop Now" in data["call_to_action"]


async def test_product_reel_generation_integration():
    """Tests content_type='reel', verifying reel job creation with product details."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_reel_job = {
        "job_id": "reel_job_abc123",
        "status": "queued",
        "progress": 0,
        "message": "Reel generation job initialized"
    }

    with patch("app.services.reel_service.ReelService.create_reel_job", new_callable=AsyncMock) as mock_job, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock):

        mock_job.return_value = mock_reel_job

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Titanium Diver Watch",
                    "product_description": "300m water resistant titanium dive watch.",
                    "price": 24999.0,
                    "content_type": "reel",
                    "use_brand_kit": False,
                }
            )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["job_id"] == "reel_job_abc123"
        assert data["data"]["status"] == "queued"


# ============================================================================
# 4. BRAND KIT ON VS OFF MODE TESTS
# ============================================================================

async def test_product_generation_brand_kit_on():
    """When use_brand_kit=True, Brand Kit is resolved from MongoDB and applied with logo overlay."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id, brand_name="Apex Luxury", primary_color="#1E3A8A")

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Apex Luxury Collection", "caption": "Elegance redefined.", "call_to_action": "Explore"}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.utils.image_composer.ImageComposer.apply_logo_overlay", new_callable=AsyncMock) as mock_overlay, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/raw_post.jpg"}
        mock_overlay.return_value = "https://example.com/composited_post.jpg"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Artisanal Silk Scarf",
                    "use_brand_kit": True,
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["use_brand_kit"] is True
        assert data["brand_kit_applied"] is True
        assert data["brand_details"]["brand_name"] == "Apex Luxury"
        assert data["brand_details"]["primary_color"] == "#1E3A8A"
        assert data["brand_details"]["logo_applied"] is True
        assert data["image_url"] == "https://example.com/composited_post.jpg"


async def test_product_generation_brand_kit_off_uses_manual_settings():
    """When use_brand_kit=False, manual settings are used and saved Brand Kit is ignored."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    # Business has Brand Kit with primary_color #1E3A8A
    await setup_business_and_brand_kit(db, user_id, brand_name="Apex Luxury", primary_color="#1E3A8A")

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Streetwear Vibe", "caption": "Rebel style.", "call_to_action": "Shop"}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/manual_post.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Oversized Graphic Tee",
                    "use_brand_kit": False,
                    "brand_name": "Urban Savage",
                    "brand_voice": "Gritty, edgy, rebellious",
                    "brand_colors": ["#000000", "#FF0055"],
                }
            )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["use_brand_kit"] is False
        assert data["brand_kit_applied"] is False
        assert data.get("brand_details") is None
        assert data.get("manual_branding_applied") is True
        assert data["manual_brand"]["brand_name"] == "Urban Savage"


async def test_product_generation_brand_kit_on_missing_returns_400():
    """When use_brand_kit=True but user has no Brand Kit in MongoDB, returns 400 BRAND_KIT_MISSING."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    # User has business but NO brand kit

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "product_name": "Test Product",
                "use_brand_kit": True,
            }
        )

    assert res.status_code == 400
    detail = res.json()["detail"]
    assert (isinstance(detail, dict) and detail.get("code") == "BRAND_KIT_MISSING") or "BRAND_KIT_MISSING" in str(detail)


# ============================================================================
# 5. AUTHORIZATION & OWNERSHIP TESTS
# ============================================================================

async def test_cross_user_product_access_denied():
    """Verifies that User B cannot generate content using Product A belonging to User A (HTTP 403)."""
    db = get_database()
    user_a_id, _, _ = await create_user_with_token(db, name="Owner User")
    biz_a_id, _, _ = await setup_business_and_brand_kit(db, user_a_id, brand_name="Owner Business")
    product_a_id, _ = await insert_test_product(db, biz_a_id, name="Secret Proprietary Drone", price=99999.0)

    # User B (Attacker)
    user_b_id, token_b, _ = await create_user_with_token(db, name="Attacker User")
    await setup_business_and_brand_kit(db, user_b_id, brand_name="Attacker Business")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "product_id": product_a_id,
                "use_brand_kit": False,
            }
        )

    assert res.status_code == 403
    assert "belongs to another business" in res.json()["detail"]


async def test_unauthenticated_request_rejected():
    """Verifies unauthenticated requests to generate content return 401 or 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            json={"product_name": "Test"}
        )

    assert res.status_code in [401, 403]


# ============================================================================
# 6. VALIDATION & FAILURE SCENARIOS
# ============================================================================

async def test_nonexistent_product_id_returns_404():
    """Verifies that referencing a non-existent ObjectId product returns 404 Not Found."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    random_id = str(ObjectId())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "product_id": random_id,
                "use_brand_kit": False,
            }
        )

    assert res.status_code == 404
    assert "not found" in res.json()["detail"]


async def test_negative_price_validation_fails():
    """Verifies that negative product price triggers Pydantic 422 Unprocessable Entity."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "product_name": "Test Product",
                "price": -100.0,
            }
        )

    assert res.status_code == 422


async def test_invalid_local_image_reference_returns_400():
    """Verifies that referencing a non-existent local uploads/ path returns 400 Bad Request."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/content/generate-post",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "product_name": "Test Product",
                "product_images": ["http://localhost:8000/uploads/products/does_not_exist_9999.jpg"],
                "use_brand_kit": False,
            }
        )

    assert res.status_code == 400
    assert "does not exist on server" in res.json()["detail"]


# ============================================================================
# 7. CONTENT LIBRARY PERSISTENCE & RETRIEVAL
# ============================================================================

async def test_content_library_storage_and_retrieval():
    """Verifies that generated content is stored in db.contents and retrievable via GET /api/v1/content."""
    db = get_database()
    user_id, token, _ = await create_user_with_token(db)
    await setup_business_and_brand_kit(db, user_id)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = '{"headline": "Library Stored Post", "caption": "Persistence test.", "call_to_action": "Click"}'

    with patch("app.ai.services.post_generation.PostGenerationService._get_gemini_client") as mock_client, \
         patch("app.ai.image.generator.ImageGenerator.generate", new_callable=AsyncMock) as mock_img_gen, \
         patch("app.services.credit_service.CreditService.check_credits", new_callable=AsyncMock), \
         patch("app.services.credit_service.CreditService.deduct_credits", new_callable=AsyncMock):

        client_inst = MagicMock()
        client_inst.models.generate_content.return_value = mock_gemini_resp
        mock_client.return_value = client_inst
        mock_img_gen.return_value = {"image_url": "https://example.com/lib.jpg"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            gen_res = await ac.post(
                "/api/v1/content/generate-post",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product_name": "Persisted Product",
                    "use_brand_kit": False,
                }
            )
            assert gen_res.status_code == 200
            content_id = gen_res.json()["data"]["_id"]

            # Retrieve all contents
            list_res = await ac.get(
                "/api/v1/content",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert list_res.status_code == 200
            items = list_res.json()["data"]
            assert any(item["_id"] == content_id for item in items)

            # Retrieve single content
            single_res = await ac.get(
                f"/api/v1/content/{content_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert single_res.status_code == 200
            assert single_res.json()["data"]["_id"] == content_id
            assert single_res.json()["data"]["headline"] == "Library Stored Post"
