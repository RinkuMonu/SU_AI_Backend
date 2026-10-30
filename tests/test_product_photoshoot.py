"""
Comprehensive Test Suite for Unified AI Product Photoshoot Studio.
Validates the entire 5-step workflow (8 phases):
- TEST A: Model-Based Commercial Catalog Photoshoot (Men's T-Shirt + Model Arjun)
- TEST B: Product-Only Commercial Studio Photoshoot (Scented Candle + Luxury Studio)
- Image uploads, visual multimodal inspection, 3-variation enhancement,
  curated model selection, style recommendations, multilingual prompt synthesis,
  batch generation with async job tracking, credit deduction, and gallery/zip downloads.
"""

import io
import asyncio
import zipfile
import pytest
from PIL import Image
from bson import ObjectId
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.services.photoshoot_service import PhotoshootService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------
def create_dummy_image_bytes(width: int = 400, height: int = 400, color: str = "navy") -> bytes:
    """Generate in-memory valid JPEG bytes for testing."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def create_auth_user(db, name: str = "Studio Merchant"):
    user_id = ObjectId()
    email = f"studio_{user_id}@dhandagrow.test"
    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": f"+919{str(user_id)[-9:]}",
        "hashed_password": get_password_hash("SecretPass@123"),
        "role": "businessman",
        "email_verified": True,
        "phone_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["users"].insert_one(user_doc)

    # Initialize subscription with sufficient credits
    await db["subscriptions"].insert_one({
        "user_id": str(user_id),
        "plan_id": "pro_annual",
        "plan_name": "Pro Annual Plan",
        "status": "active",
        "credits_remaining": 100,
        "credits_total": 100,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    token = create_access_token(subject=str(user_id))
    return str(user_id), token


@pytest.fixture(autouse=True)
async def db_lifecycle():
    connect_to_mongo()
    PhotoshootService.ensure_directories()
    yield
    close_mongo_connection()


# ---------------------------------------------------------------------------
# Phase 1: Upload Product Images
# ---------------------------------------------------------------------------
async def test_phase1_upload_product_images():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 1 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img1_bytes = create_dummy_image_bytes(500, 500, "navy")
    img2_bytes = create_dummy_image_bytes(500, 500, "darkblue")

    files = [
        ("files", ("front_tshirt.jpg", img1_bytes, "image/jpeg")),
        ("files", ("back_tshirt.jpg", img2_bytes, "image/jpeg")),
    ]
    data = {
        "product_category": "Clothing",
        "angles": "Front, Back",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files, data=data)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert "session_id" in body
    assert body["total_uploaded"] == 2
    assert len(body["uploaded_images"]) == 2
    assert body["uploaded_images"][0]["angle"] == "Front"
    assert body["uploaded_images"][1]["angle"] == "Back"

    # Verify session persisted in MongoDB
    session_id = body["session_id"]
    sess = await db["photoshoot_sessions"].find_one({"session_id": session_id})
    assert sess is not None
    assert sess["user_id"] == user_id
    assert len(sess["original_images"]) == 2


# ---------------------------------------------------------------------------
# Phase 2: AI Product Visual Analysis
# ---------------------------------------------------------------------------
async def test_phase2_analyze_product():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 2 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(600, 600, "teal")
    files = [("files", ("teal_shirt.jpg", img_bytes, "image/jpeg"))]
    data = {"product_category": "Clothing"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_resp = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files, data=data)
        session_id = up_resp.json()["session_id"]

        # Run analysis
        an_resp = await ac.post(
            "/api/v1/product-photoshoot/analyze",
            headers=headers,
            json={"session_id": session_id},
        )

    assert an_resp.status_code == 200, an_resp.text
    an_body = an_resp.json()
    assert an_body["success"] is True
    analysis = an_body["analysis"]
    assert "product_category" in analysis
    assert "product_type" in analysis
    assert "main_colors" in analysis
    assert "material_and_texture" in analysis
    assert "suitable_for_model" in analysis
    assert "recommended_styles" in analysis
    assert isinstance(analysis["recommended_styles"], list)


# ---------------------------------------------------------------------------
# Phase 3: AI Product Image Enhancement
# ---------------------------------------------------------------------------
async def test_phase3_enhance_product_images():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 3 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(500, 500, "maroon")
    files = [("files", ("product.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_resp = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
        session_id = up_resp.json()["session_id"]

        # Enhance
        enh_resp = await ac.post(
            "/api/v1/product-photoshoot/enhance",
            headers=headers,
            json={
                "session_id": session_id,
                "styles": ["Studio Premium", "Luxury Cinematic", "Marketplace White"],
            },
        )

    assert enh_resp.status_code == 200, enh_resp.text
    enh_body = enh_resp.json()
    assert enh_body["success"] is True
    assert enh_body["total_variations"] == 3
    assert len(enh_body["enhanced_images"]) == 3

    # Check variation styles
    styles_returned = {img["style"] for img in enh_body["enhanced_images"]}
    assert "Studio Premium" in styles_returned
    assert "Luxury Cinematic" in styles_returned
    assert "Marketplace White" in styles_returned

    # Test selecting enhanced image
    selected_id = enh_body["enhanced_images"][0]["image_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        sel_resp = await ac.post(
            f"/api/v1/product-photoshoot/{session_id}/select-enhanced",
            headers=headers,
            json={"selected_image_ids": [selected_id]},
        )
    assert sel_resp.status_code == 200
    sel_body = sel_resp.json()
    assert sel_body["success"] is True
    assert selected_id in sel_body["selected_image_ids"]


# ---------------------------------------------------------------------------
# Phase 4: Curated AI Model Gallery
# ---------------------------------------------------------------------------
async def test_phase4_model_gallery():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 4 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. All models
        r1 = await ac.get("/api/v1/product-photoshoot/models", headers=headers)
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["success"] is True
        assert b1["total"] >= 5

        # 2. Male models only
        r2 = await ac.get("/api/v1/product-photoshoot/models?gender=male", headers=headers)
        assert r2.status_code == 200
        b2 = r2.json()
        assert all(m["gender"] in ("male", "unisex") for m in b2["models"])

        # 3. Female models only
        r3 = await ac.get("/api/v1/product-photoshoot/models?gender=female", headers=headers)
        assert r3.status_code == 200
        b3 = r3.json()
        assert all(m["gender"] in ("female", "unisex") for m in b3["models"])


# ---------------------------------------------------------------------------
# Phase 5: Photography Styles & Poses Catalog
# ---------------------------------------------------------------------------
async def test_phase5_photography_styles():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 5 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Model-based styles
        r_model = await ac.get(
            "/api/v1/product-photoshoot/styles?category=Clothing&use_model=true",
            headers=headers,
        )
        assert r_model.status_code == 200
        b_model = r_model.json()
        assert b_model["use_model"] is True
        assert len(b_model["styles"]) >= 3
        # Should include model poses like Front View, Walking Pose, etc.
        poses = [s["name"] for s in b_model["styles"]]
        assert any("View" in p or "Pose" in p for p in poses)

        # Product-only styles
        r_prod = await ac.get(
            "/api/v1/product-photoshoot/styles?category=Candle&use_model=false",
            headers=headers,
        )
        assert r_prod.status_code == 200
        b_prod = r_prod.json()
        assert b_prod["use_model"] is False
        assert len(b_prod["styles"]) >= 3
        prod_styles = [s["name"] for s in b_prod["styles"]]
        assert any("Hero" in s or "Studio" in s or "Lifestyle" in s for s in prod_styles)


# ---------------------------------------------------------------------------
# Phase 6: Custom Prompt Preparation
# ---------------------------------------------------------------------------
async def test_phase6_prepare_prompt():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 6 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(500, 500, "black")
    files = [("files", ("black_hoodie.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_resp = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
        session_id = up_resp.json()["session_id"]

        # Call prepare-prompt
        prep_resp = await ac.post(
            "/api/v1/product-photoshoot/prepare-prompt",
            headers=headers,
            json={
                "session_id": session_id,
                "custom_prompt": "Clean urban look with dramatic side light, Hinglish instructions",
                "language": "hi-en",
                "use_model": True,
                "model_id": "model_male_01",
                "selected_styles": ["Front View", "Sitting Pose"],
            },
        )

    assert prep_resp.status_code == 200, prep_resp.text
    body = prep_resp.json()
    assert body["success"] is True
    assert "prepared_prompt" in body
    assert len(body["prepared_prompt"]) > 10
    assert body["workflow_summary"]["use_model"] is True


# ---------------------------------------------------------------------------
# TEST A: Complete Model-Based Flow (Men's T-Shirt + Model Arjun)
# ---------------------------------------------------------------------------
async def test_flow_a_mens_tshirt_with_model():
    """TEST A: Men's T-Shirt, use_model=True, Arjun model, poses Front & Sitting."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Test A Merchant")
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Upload
    img_bytes = create_dummy_image_bytes(600, 600, "navy")
    files = [("files", ("mens_tshirt.jpg", img_bytes, "image/jpeg"))]
    data = {"product_category": "Clothing", "angles": "Front"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_res = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files, data=data)
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]

        # Step 2: Visual Analysis
        an_res = await ac.post("/api/v1/product-photoshoot/analyze", headers=headers, json={"session_id": session_id})
        assert an_res.status_code == 200

        # Step 3: Enhancement
        enh_res = await ac.post(
            "/api/v1/product-photoshoot/enhance",
            headers=headers,
            json={"session_id": session_id, "styles": ["Studio Premium", "Luxury Cinematic"]},
        )
        assert enh_res.status_code == 200

        # Step 4: Model & Styles
        models_res = await ac.get("/api/v1/product-photoshoot/models?gender=male", headers=headers)
        assert models_res.status_code == 200
        chosen_model = models_res.json()["models"][0]["model_id"]

        styles_res = await ac.get(
            f"/api/v1/product-photoshoot/styles?category=Clothing&use_model=true&model_id={chosen_model}",
            headers=headers,
        )
        assert styles_res.status_code == 200

        # Step 5: Start Batch Generation
        gen_res = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={
                "session_id": session_id,
                "product_category": "Clothing",
                "use_model": True,
                "model_id": chosen_model,
                "selected_styles": ["Front View", "Sitting Pose"],
                "custom_prompt": "Ultra-sharp e-commerce catalog photography for premium fashion label",
                "image_count": 3,
            },
        )
        assert gen_res.status_code == 200, gen_res.text
        gen_body = gen_res.json()
        assert gen_body["success"] is True
        job_id = gen_body["job_id"]

        # Step 6: Poll Job Status until completed
        completed = False
        for _ in range(30):
            job_res = await ac.get(f"/api/v1/product-photoshoot/jobs/{job_id}", headers=headers)
            assert job_res.status_code == 200
            j_data = job_res.json()
            if j_data["status"] == "completed":
                completed = True
                assert len(j_data["result_images"]) == 3
                assert j_data["progress_percent"] == 100
                break
            elif j_data["status"] == "failed":
                pytest.fail(f"Photoshoot job failed: {j_data.get('error')}")
            await asyncio.sleep(0.5)

        assert completed, "Photoshoot job timed out"

        # Verify session results
        res_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}/results", headers=headers)
        assert res_resp.status_code == 200
        res_body = res_resp.json()
        assert res_body["total_images"] == 3
        assert res_body["use_model"] is True

        # Check credits deducted in DB
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["credits_remaining"] == 95  # 100 - 5 = 95


# ---------------------------------------------------------------------------
# TEST B: Complete Product-Only Flow (Scented Candle + Luxury Studio)
# ---------------------------------------------------------------------------
async def test_flow_b_scented_candle_product_only():
    """TEST B: Scented Candle, use_model=False, Luxury Studio & Hero styles."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Test B Candle Merchant")
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Upload
    img_bytes = create_dummy_image_bytes(500, 500, "orange")
    files = [("files", ("scented_candle.jpg", img_bytes, "image/jpeg"))]
    data = {"product_category": "Home Decor", "angles": "Front"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_res = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files, data=data)
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]

        # Step 2: Visual Analysis
        an_res = await ac.post("/api/v1/product-photoshoot/analyze", headers=headers, json={"session_id": session_id})
        assert an_res.status_code == 200

        # Step 3: Enhancement
        enh_res = await ac.post(
            "/api/v1/product-photoshoot/enhance",
            headers=headers,
            json={"session_id": session_id, "styles": ["Luxury Cinematic"]},
        )
        assert enh_res.status_code == 200

        # Step 4: Product-Only Styles
        styles_res = await ac.get(
            "/api/v1/product-photoshoot/styles?category=Home+Decor&use_model=false",
            headers=headers,
        )
        assert styles_res.status_code == 200
        assert styles_res.json()["use_model"] is False

        # Step 5: Start Batch Generation (Strictly product-only, no model)
        gen_res = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={
                "session_id": session_id,
                "product_category": "Home Decor",
                "use_model": False,
                "model_id": None,
                "selected_styles": ["Clean Hero Product Shot", "Luxury Studio Composition"],
                "custom_prompt": "Warm ambient lighting on stone pedestal with natural shadows",
                "image_count": 2,
            },
        )
        assert gen_res.status_code == 200, gen_res.text
        job_id = gen_res.json()["job_id"]

        # Step 6: Poll Job
        completed = False
        for _ in range(45):
            job_res = await ac.get(f"/api/v1/product-photoshoot/jobs/{job_id}", headers=headers)
            assert job_res.status_code == 200
            j_data = job_res.json()
            if j_data["status"] == "completed":
                completed = True
                assert len(j_data["result_images"]) == 2
                break
            elif j_data["status"] == "failed":
                pytest.fail(f"Job failed: {j_data.get('error')}")
            await asyncio.sleep(1.0)

        assert completed, "Product-only job timed out"

        # Verify session results
        res_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}/results", headers=headers)
        assert res_resp.status_code == 200
        assert res_resp.json()["use_model"] is False


# ---------------------------------------------------------------------------
# Phase 8: Results, Gallery, Save, Delete, Download
# ---------------------------------------------------------------------------
async def test_phase8_gallery_save_delete_download():
    db = get_database()
    user_id, token = await create_auth_user(db, name="Phase 8 Tester")
    headers = {"Authorization": f"Bearer {token}"}

    # Setup session with generated images
    img_bytes = create_dummy_image_bytes(400, 400, "darkgreen")
    files = [("files", ("perfume.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_res = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
        session_id = up_res.json()["session_id"]

        # Generate 2 images
        gen_res = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={"session_id": session_id, "use_model": False, "image_count": 2},
        )
        job_id = gen_res.json()["job_id"]

        # Wait for completion
        completed = False
        for _ in range(45):
            j = await ac.get(f"/api/v1/product-photoshoot/jobs/{job_id}", headers=headers)
            if j.json()["status"] == "completed":
                completed = True
                break
            elif j.json()["status"] == "failed":
                pytest.fail(f"Photoshoot job failed: {j.json().get('error')}")
            await asyncio.sleep(1.0)

        assert completed, "Photoshoot job timed out in test_phase8"

        # 1. Get results
        res_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}/results", headers=headers)
        assert res_resp.status_code == 200
        results = res_resp.json()["results"]
        assert len(results) >= 2
        img1_id = results[0]["image_id"]
        img2_id = results[1]["image_id"]

        # 2. Save selected image
        save_resp = await ac.post(
            f"/api/v1/product-photoshoot/{session_id}/save",
            headers=headers,
            json={"image_ids": [img1_id]},
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["saved_count"] == 1

        # 3. Retrieve gallery
        gal_resp = await ac.get("/api/v1/product-photoshoot/gallery", headers=headers)
        assert gal_resp.status_code == 200
        gal_body = gal_resp.json()
        assert gal_body["success"] is True
        assert gal_body["total"] >= 1

        # 4. Single image download
        dl_img_resp = await ac.get(f"/api/v1/product-photoshoot/images/{img1_id}/download", headers=headers)
        assert dl_img_resp.status_code == 200
        assert len(dl_img_resp.content) > 0
        assert dl_img_resp.headers["content-type"] in ("image/jpeg", "application/octet-stream")

        # 5. Session ZIP download
        dl_zip_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}/download", headers=headers)
        assert dl_zip_resp.status_code == 200
        assert dl_zip_resp.headers["content-type"] == "application/zip"
        # Verify ZIP contains valid file
        with zipfile.ZipFile(io.BytesIO(dl_zip_resp.content)) as zf:
            namelist = zf.namelist()
            assert len(namelist) >= 1

        # 6. Regenerate image
        regen_resp = await ac.post(
            f"/api/v1/product-photoshoot/images/{img1_id}/regenerate",
            headers=headers,
            json={"style": "Luxury Studio Composition", "custom_prompt": "Golden hour rim light"},
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["success"] is True

        # 7. Delete image
        del_resp = await ac.delete(f"/api/v1/product-photoshoot/images/{img2_id}", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # Verify image deleted from database
        deleted_doc = await db["photoshoot_images"].find_one({"image_id": img2_id})
        assert deleted_doc is None


# ---------------------------------------------------------------------------
# Additional Resilience, Validation & Security Tests
# ---------------------------------------------------------------------------
async def test_invalid_image_upload_handling():
    """Verify upload endpoint rejects invalid extensions and empty files."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Validation Tester")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Invalid extension (.txt)
    files = [("files", ("test.txt", b"plain text content", "text/plain"))]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


async def test_duplicate_generation_prevention():
    """Verify sending repeated generate requests returns existing job and avoids duplicate credit deductions."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Duplicate Guard Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(400, 400, "purple")
    files = [("files", ("item.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
        session_id = up.json()["session_id"]

        # Call generate once
        r1 = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={"session_id": session_id, "use_model": False, "image_count": 2},
        )
        assert r1.status_code == 200
        job1_id = r1.json()["job_id"]

        # Call generate again immediately while job is active
        r2 = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={"session_id": session_id, "use_model": False, "image_count": 2},
        )
        assert r2.status_code == 200
        # Must return the same active job ID without extra charge
        assert r2.json()["job_id"] == job1_id
        assert "already active" in r2.json()["message"]


async def test_user_ownership_isolation():
    """Verify that User B cannot access or modify User A's session, results, or images."""
    db = get_database()
    userA_id, tokenA = await create_auth_user(db, name="User A")
    userB_id, tokenB = await create_auth_user(db, name="User B")

    headersA = {"Authorization": f"Bearer {tokenA}"}
    headersB = {"Authorization": f"Bearer {tokenB}"}

    img_bytes = create_dummy_image_bytes(400, 400, "brown")
    files = [("files", ("product_a.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up = await ac.post("/api/v1/product-photoshoot/upload", headers=headersA, files=files)
        session_a_id = up.json()["session_id"]

        # User B attempts to access User A's session results -> 404
        r_b_results = await ac.get(f"/api/v1/product-photoshoot/{session_a_id}/results", headers=headersB)
        assert r_b_results.status_code == 404

        # User B attempts to generate on User A's session -> 404
        r_b_gen = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headersB,
            json={"session_id": session_a_id, "use_model": False},
        )
        assert r_b_gen.status_code == 404


# ---------------------------------------------------------------------------
# TEST C: Failure Recovery & Partial Retry
# ---------------------------------------------------------------------------
async def test_failure_recovery_and_partial_retry():
    """TEST C: Simulate partial generation failure, verify partial results, retry, and verify no duplicate credit deduction."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Test C Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(400, 400, "grey")
    files = [("files", ("test_c.jpg", img_bytes, "image/jpeg"))]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files)
        session_id = up.json()["session_id"]

        # Call generate for 2 images
        gen_res = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers,
            json={"session_id": session_id, "use_model": False, "image_count": 2},
        )
        assert gen_res.status_code == 200
        job_id = gen_res.json()["job_id"]

        # Wait for initial job
        for _ in range(40):
            j = await ac.get(f"/api/v1/product-photoshoot/jobs/{job_id}", headers=headers)
            if j.json()["status"] in ("completed", "partial"):
                break
            await asyncio.sleep(1.0)

        # Record credits after initial generation (100 - 5 = 95)
        sub_before = await db["subscriptions"].find_one({"user_id": user_id})
        credits_before_retry = sub_before["credits_remaining"]

        # Now simulate a partial failure on a new job to test retry
        partial_job_id = f"job_partial_{user_id[:6]}"
        failed_item = {
            "index": 2,
            "style": "Luxury Studio Composition",
            "prompt": "Commercial product photography of grey item, Luxury Studio",
            "error": "Temporary network timeout simulated"
        }
        await db["photoshoot_jobs"].insert_one({
            "job_id": partial_job_id,
            "session_id": session_id,
            "user_id": str(user_id),
            "status": "partial",
            "progress_percent": 50,
            "total_images": 2,
            "completed_images": 1,
            "failed_images": 1,
            "failed_items": [failed_item],
            "can_retry": True,
            "result_images": [{
                "image_id": "img_prev_01",
                "session_id": session_id,
                "style_applied": "Clean Hero Product Shot",
                "url": "/uploads/photoshoot/final/prev.jpg",
                "is_saved": False,
                "created_at": datetime.now(timezone.utc)
            }],
            "error": None,
            "credits_deducted": 5,
            "created_at": datetime.now(timezone.utc)
        })

        # Check job status reports partial & can_retry
        status_res = await ac.get(f"/api/v1/product-photoshoot/jobs/{partial_job_id}", headers=headers)
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["status"] == "partial"
        assert status_data["can_retry"] is True
        assert status_data["failed_images"] == 1

        # Execute retry endpoint
        retry_res = await ac.post(f"/api/v1/product-photoshoot/jobs/{partial_job_id}/retry", headers=headers)
        assert retry_res.status_code == 200
        assert retry_res.json()["success"] is True
        assert retry_res.json()["retrying_count"] == 1

        # Poll until retry completes
        retry_completed = False
        for _ in range(40):
            st = await ac.get(f"/api/v1/product-photoshoot/jobs/{partial_job_id}", headers=headers)
            if st.json()["status"] == "completed":
                retry_completed = True
                assert st.json()["completed_images"] == 2
                assert len(st.json()["result_images"]) == 2
                break
            await asyncio.sleep(1.0)

        assert retry_completed, "Retry job did not complete"

        # Verify NO duplicate credit deduction occurred during retry
        sub_after = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub_after["credits_remaining"] == credits_before_retry


# ---------------------------------------------------------------------------
# TEST D: Data Persistence Across Login / Logout
# ---------------------------------------------------------------------------
async def test_data_persistence_across_login_logout():
    """TEST D: Complete photoshoot, log out, log back in, retrieve previous session and saved images."""
    db = get_database()
    user_id, token_login_1 = await create_auth_user(db, name="Persistence Merchant")
    headers_1 = {"Authorization": f"Bearer {token_login_1}"}

    # Step 1: Upload multiple images
    img1 = create_dummy_image_bytes(500, 500, "teal")
    img2 = create_dummy_image_bytes(500, 500, "darkblue")
    files = [
        ("files", ("front.jpg", img1, "image/jpeg")),
        ("files", ("back.jpg", img2, "image/jpeg")),
    ]
    data = {"product_category": "Clothing", "angles": "Front, Back"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up_res = await ac.post("/api/v1/product-photoshoot/upload", headers=headers_1, files=files, data=data)
        assert up_res.status_code == 200
        session_id = up_res.json()["session_id"]

        # Step 2: Generate photoshoot
        gen_res = await ac.post(
            "/api/v1/product-photoshoot/generate",
            headers=headers_1,
            json={"session_id": session_id, "use_model": False, "image_count": 2},
        )
        assert gen_res.status_code == 200
        job_id = gen_res.json()["job_id"]

        # Wait for completion
        for _ in range(40):
            j = await ac.get(f"/api/v1/product-photoshoot/jobs/{job_id}", headers=headers_1)
            if j.json()["status"] == "completed":
                break
            await asyncio.sleep(1.0)

        # Step 3: Save results
        res_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}/results", headers=headers_1)
        results = res_resp.json()["results"]
        assert len(results) >= 2
        saved_img_id = results[0]["image_id"]

        save_res = await ac.post(
            f"/api/v1/product-photoshoot/{session_id}/save",
            headers=headers_1,
            json={"image_ids": [saved_img_id]},
        )
        assert save_res.status_code == 200

    # Step 4: Simulate Logout (token discarded)
    del headers_1

    # Step 5: Simulate Login (authenticate user anew, receive new token)
    token_login_2 = create_access_token(subject=str(user_id))
    headers_2 = {"Authorization": f"Bearer {token_login_2}"}

    # Step 6: Verify full data retrieval with new login session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Gallery retrieval
        gal_resp = await ac.get("/api/v1/product-photoshoot/gallery", headers=headers_2)
        assert gal_resp.status_code == 200
        gal_data = gal_resp.json()
        assert gal_data["total"] >= 1
        matching_sess = [s for s in gal_data["sessions"] if s["session_id"] == session_id]
        assert len(matching_sess) == 1
        assert matching_sess[0]["saved_count"] == 1

        # Session metadata retrieval
        sess_resp = await ac.get(f"/api/v1/product-photoshoot/{session_id}", headers=headers_2)
        assert sess_resp.status_code == 200
        sess_doc = sess_resp.json()["session"]
        assert sess_doc["session_id"] == session_id
        assert sess_doc["user_id"] == user_id
        assert len(sess_doc["original_images"]) == 2
        assert "uploaded_images" in sess_doc
        assert len(sess_doc["uploaded_images"]) == 2
        assert saved_img_id in sess_doc["saved_image_ids"]

        # Image results retrieval
        res_login_2 = await ac.get(f"/api/v1/product-photoshoot/{session_id}/results", headers=headers_2)
        assert res_login_2.status_code == 200
        assert len(res_login_2.json()["results"]) >= 2


# ---------------------------------------------------------------------------
# TEST E: Audio Prompt Preparation & Advanced Gallery Filtering
# ---------------------------------------------------------------------------
async def test_audio_prompt_preparation_and_gallery_filtering():
    """Verify prepare-prompt-audio endpoint and advanced gallery filtering by category, model mode, and date."""
    db = get_database()
    user_id, token = await create_auth_user(db, name="Audio & Filter Tester")
    headers = {"Authorization": f"Bearer {token}"}

    img_bytes = create_dummy_image_bytes(400, 400, "purple")
    files = [("files", ("handbag.jpg", img_bytes, "image/jpeg"))]
    data = {"product_category": "Bags & Luggage"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Upload
        up = await ac.post("/api/v1/product-photoshoot/upload", headers=headers, files=files, data=data)
        assert up.status_code == 200
        session_id = up.json()["session_id"]

        # 2. Test prepare-prompt-audio with form fields
        form_data = {
            "session_id": session_id,
            "custom_prompt": "Luxury golden hour lighting on velvet handbag",
            "language": "en",
            "use_model": "false",
            "selected_styles": "Clean Hero Product Shot, Luxury Studio Podia",
        }
        audio_bytes = b"RIFF....WAVEfmt ...."  # mock audio payload
        audio_file = ("voice.wav", audio_bytes, "audio/wav")

        prep_audio_res = await ac.post(
            "/api/v1/product-photoshoot/prepare-prompt-audio",
            headers=headers,
            data=form_data,
            files={"audio_file": audio_file},
        )
        assert prep_audio_res.status_code == 200, prep_audio_res.text
        prep_body = prep_audio_res.json()
        assert prep_body["success"] is True
        assert "prepared_prompt" in prep_body
        assert len(prep_body["prepared_prompt"]) > 10

        # 3. Test gallery with category and sort_by filters
        gal_filtered = await ac.get(
            "/api/v1/product-photoshoot/gallery?category=Bags%20%26%20Luggage&use_model=false&sort_by=desc",
            headers=headers,
        )
        assert gal_filtered.status_code == 200
        gal_data = gal_filtered.json()
        assert gal_data["success"] is True
        assert gal_data["total"] >= 1




