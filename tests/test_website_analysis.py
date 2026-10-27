import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token, get_password_hash
from app.utils.url_validator import normalize_website_url, validate_url_safety
from app.services.website_analysis_service import WebsiteAnalysisService
from app.schemas.website_analysis import (
    BrandVoiceResult,
    BrandColorsResult,
    BrandCategoryResult,
    PhotoItem,
    WebsiteAnalysisResults
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Aurora Luxe - Sustainable Modern Apparel</title>
    <meta name="description" content="Handcrafted ethical fashion made from 100% organic materials for mindful living.">
    <meta property="og:title" content="Aurora Luxe Ethical Fashion">
    <meta property="og:description" content="Discover mindful luxury fashion designed to elevate everyday style.">
    <meta property="og:site_name" content="Aurora Luxe">
    <meta property="og:image" content="https://auroraluxe.example.com/images/og-hero.jpg">
    <meta name="theme-color" content="#6C5CE7">
    <style>
        :root {
            --brand-primary: #6C5CE7;
            --brand-secondary: #FD79A8;
            --brand-accent: #00CEC9;
        }
        .header { background: #6C5CE7; color: #FFFFFF; }
        .cta-btn { background: #00CEC9; border: 2px solid #FD79A8; }
    </style>
</head>
<body>
    <header>
        <img src="/assets/logo-main.png" alt="Aurora Luxe Logo" class="brand-logo" id="site-logo" />
        <h1>Timeless Sustainable Elegance</h1>
    </header>
    <main>
        <div class="hero-section">
            <img src="/media/hero-banner.jpg" class="hero-image" alt="Aurora Spring Collection" />
            <p>We blend luxury European tailoring with certified organic textiles to create clothing that lasts a lifetime.</p>
        </div>
        <section class="products">
            <h2>Our Signature Collection</h2>
            <p>Every piece is made by master artisans dedicated to ethical sustainability.</p>
            <img src="/catalog/organic-linen-blazer.jpg" alt="Organic Linen Blazer" class="product-item" />
            <img src="/catalog/silk-slip-dress.jpg" alt="Pure Silk Slip Dress" class="product-item" />
        </section>
    </main>
</body>
</html>
"""


@pytest.fixture(autouse=True)
def ensure_db():
    connect_to_mongo()


@pytest.fixture
async def auth_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Website Tester",
        "email": f"webtest_{str(uid)[-6:]}@onboarding-test.com",
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


@pytest.fixture
async def auth_user2():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Website Tester 2",
        "email": f"webtest2_{str(uid)[-6:]}@onboarding-test.com",
        "phone_number": f"+9197{str(uid)[-8:]}",
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


# --------------------------------------------------------------------------
# 1. URL Normalization & Validation Unit Tests
# --------------------------------------------------------------------------

def test_normalize_website_url():
    assert normalize_website_url("dhandagrow.com") == "https://dhandagrow.com/"
    assert normalize_website_url("www.zara.com/in/en") == "https://www.zara.com/in/en"
    assert normalize_website_url("http://example.com/store") == "http://example.com/store"
    assert normalize_website_url("HTTPS://MYBRAND.CO.IN/") == "https://mybrand.co.in/"


def test_normalize_website_url_invalid():
    with pytest.raises(Exception):
        normalize_website_url("")

    with pytest.raises(Exception):
        normalize_website_url("javascript:alert(1)")

    with pytest.raises(Exception):
        normalize_website_url("file:///etc/passwd")

    with pytest.raises(Exception):
        normalize_website_url("ftp://ftp.example.com")

    with pytest.raises(Exception):
        normalize_website_url("justwords")


def test_validate_url_safety_ssrf():
    is_safe, err = validate_url_safety("http://localhost:8000")
    assert not is_safe
    assert "restricted" in err.lower() or "localhost" in err.lower()

    is_safe, err = validate_url_safety("http://127.0.0.1:3000")
    assert not is_safe

    is_safe, err = validate_url_safety("http://169.254.169.254/latest/meta-data/")
    assert not is_safe

    is_safe, err = validate_url_safety("http://10.0.0.5/admin")
    assert not is_safe

    is_safe, err = validate_url_safety("http://192.168.1.1")
    assert not is_safe

    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]
        is_safe, err = validate_url_safety("https://example.com")
        assert is_safe
        assert err is None


# --------------------------------------------------------------------------
# 2. HTML Asset & Color Extraction Tests
# --------------------------------------------------------------------------

def test_parse_html_content_extraction():
    base_url = "https://auroraluxe.example.com"
    extracted = WebsiteAnalysisService._parse_html_content(SAMPLE_HTML, base_url)

    assert "Aurora Luxe" in extracted["title"]
    assert "organic materials" in extracted["description"]
    assert extracted["domain"] == "auroraluxe.example.com"

    colors = extracted["top_css_colors"]
    assert "#6C5CE7" in colors
    assert any(c in colors for c in ["#FD79A8", "#00CEC9"])

    photos = extracted["photos"]
    assert len(photos) >= 3

    logo = extracted["logo_candidate"]
    assert logo is not None
    assert "logo-main.png" in logo
    assert logo.startswith("https://auroraluxe.example.com/")

    hero = extracted["hero_candidate"]
    assert hero is not None
    assert "hero" in hero

    body = extracted["body_text"]
    assert "European tailoring" in body
    assert "Signature Collection" in body


# --------------------------------------------------------------------------
# 3. API Endpoints: Job Creation, SSRF Rejection, Polling Status
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_website_analysis_job_api(auth_user):
    headers, uid = auth_user

    with patch("socket.getaddrinfo") as mock_dns, patch("asyncio.create_task") as mock_task:
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/onboarding/website-analysis",
                json={
                    "url": "auroraluxe.example.com",
                    "onboarding_type": "website",
                    "business_name": "Aurora Luxe"
                },
                headers=headers
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data
        assert data["job_id"].startswith("job_")
        assert data["status"] == "pending"
        assert data["url"] == "https://auroraluxe.example.com/"
        assert data["onboarding_type"] == "website"

        db = get_database()
        job_doc = await db["website_analysis_jobs"].find_one({"job_id": data["job_id"]})
        assert job_doc is not None
        assert job_doc["user_id"] == uid
        assert job_doc["step_statuses"]["fetching"] == "pending"
        assert job_doc["step_statuses"]["brand_voice"] == "pending"
        assert job_doc["step_statuses"]["colors"] == "pending"
        assert job_doc["step_statuses"]["category"] == "pending"
        assert job_doc["step_statuses"]["photos"] == "pending"

        user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
        assert user_doc is not None
        assert user_doc.get("online_presence") == "website"


@pytest.mark.asyncio
async def test_create_website_analysis_job_rejects_ssrf(auth_user):
    headers, _ = auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp1 = await ac.post(
            "/api/v1/onboarding/website-analysis",
            json={"url": "http://localhost:8000"},
            headers=headers
        )
        assert resp1.status_code == 400
        assert "restricted" in resp1.json()["detail"].lower() or "localhost" in resp1.json()["detail"].lower()

        resp2 = await ac.post(
            "/api/v1/onboarding/website-analysis",
            json={"url": "http://169.254.169.254/latest/meta-data/"},
            headers=headers
        )
        assert resp2.status_code == 400

        resp3 = await ac.post(
            "/api/v1/onboarding/website-analysis",
            json={"url": "http://192.168.1.100"},
            headers=headers
        )
        assert resp3.status_code == 400


@pytest.mark.asyncio
async def test_poll_website_analysis_status_api(auth_user, auth_user2):
    headers1, uid1 = auth_user
    headers2, uid2 = auth_user2
    db = get_database()

    job_id = f"job_test_poll_{uid1[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid1,
        "onboarding_type": "website",
        "url": "https://auroraluxe.example.com/",
        "status": "processing",
        "progress": 65,
        "current_step": "analyzing_brand_voice",
        "step_statuses": {
            "fetching": "completed",
            "brand_voice": "in_progress",
            "colors": "pending",
            "category": "pending",
            "photos": "pending"
        },
        "results": None,
        "error": None,
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/v1/onboarding/website-analysis/{job_id}", headers=headers1)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] == "processing"
        assert data["progress"] == 65
        assert data["current_step"] == "analyzing_brand_voice"
        assert data["step_statuses"]["fetching"] == "completed"
        assert data["step_statuses"]["brand_voice"] == "in_progress"

        resp_unauthorized = await ac.get(f"/api/v1/onboarding/website-analysis/{job_id}", headers=headers2)
        assert resp_unauthorized.status_code == 404

        resp_latest = await ac.get("/api/v1/onboarding/website-analysis/latest", headers=headers1)
        assert resp_latest.status_code == 200
        assert resp_latest.json()["job_id"] == job_id


# --------------------------------------------------------------------------
# 4. End-to-End Pipeline & Profile Apply Tests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_analysis_pipeline_and_apply_to_profile(auth_user):
    headers, uid = auth_user
    db = get_database()

    target_url = "https://auroraluxe.example.com/"
    job_id = f"job_pipeline_{uid[:8]}"
    now = datetime.now(timezone.utc)

    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": target_url,
        "status": "pending",
        "progress": 0,
        "current_step": "initializing",
        "step_statuses": {
            "fetching": "pending",
            "brand_voice": "pending",
            "colors": "pending",
            "category": "pending",
            "photos": "pending"
        },
        "results": None,
        "error": None,
        "created_at": now,
        "updated_at": now
    })

    with patch.object(WebsiteAnalysisService, "_fetch_website") as mock_fetch:
        mock_fetch.return_value = (SAMPLE_HTML, target_url, None)
        await WebsiteAnalysisService.run_analysis_pipeline(db, job_id, target_url, uid)

    job_doc = await db["website_analysis_jobs"].find_one({"job_id": job_id})
    assert job_doc["status"] == "completed"
    assert job_doc["progress"] == 100
    assert job_doc["current_step"] == "completed"
    assert job_doc["step_statuses"]["fetching"] == "completed"
    assert job_doc["step_statuses"]["brand_voice"] == "completed"
    assert job_doc["step_statuses"]["colors"] == "completed"
    assert job_doc["step_statuses"]["category"] == "completed"
    assert job_doc["step_statuses"]["photos"] == "completed"

    res = job_doc["results"]
    assert res is not None
    assert "brand_voice" in res
    assert "colors" in res
    assert "category" in res
    assert "photos" in res
    assert res["colors"]["primary"] is not None
    assert len(res["photos"]) > 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp_apply = await ac.post(f"/api/v1/onboarding/website-analysis/{job_id}/apply", headers=headers)
        assert resp_apply.status_code == 200
        apply_data = resp_apply.json()
        assert apply_data["success"] is True

    brand_kit = await db["brand_kits"].find_one({"$or": [{"owner_id": uid}, {"user_id": uid}]})
    assert brand_kit is not None
    assert brand_kit.get("online_presence") == "website"
    assert brand_kit.get("primary_color") is not None
    assert brand_kit.get("brand_voice") is not None

    bus = await db["businesses"].find_one({"$or": [{"owner_id": uid}, {"ownerId": uid}]})
    assert bus is not None
    assert bus.get("website") == target_url
    assert bus.get("online_presence") == "website"


@pytest.mark.asyncio
async def test_fetch_error_handling_in_pipeline():
    db = get_database()
    uid = str(ObjectId())
    job_id = f"job_fail_{uid[:8]}"
    now = datetime.now(timezone.utc)

    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://nonexistent-store-1234.com/",
        "status": "pending",
        "progress": 0,
        "current_step": "initializing",
        "step_statuses": {
            "fetching": "pending",
            "brand_voice": "pending",
            "colors": "pending",
            "category": "pending",
            "photos": "pending"
        },
        "results": None,
        "error": None,
        "created_at": now,
        "updated_at": now
    })

    with patch.object(WebsiteAnalysisService, "_fetch_website") as mock_fetch:
        mock_fetch.return_value = (None, None, "Website returned 404 Not Found at 'https://nonexistent-store-1234.com/'.")
        await WebsiteAnalysisService.run_analysis_pipeline(db, job_id, "https://nonexistent-store-1234.com/", uid)

    job_doc = await db["website_analysis_jobs"].find_one({"job_id": job_id})
    assert job_doc["status"] == "failed"
    assert job_doc["step_statuses"]["fetching"] == "failed"
    assert "404 Not Found" in job_doc["error"]


# --------------------------------------------------------------------------
# 5. Dynamic Flow Tests (Screens 1 to 6)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_business_profile_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_profile_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://sevenunique.com/",
        "status": "completed",
        "progress": 100,
        "current_step": "completed",
        "onboarding_step": "business_details",
        "step_statuses": {
            "fetching": "completed",
            "brand_voice": "completed",
            "colors": "completed",
            "category": "completed",
            "photos": "completed"
        },
        "results": {
            "business_details": {
                "business_name": "SevenUnique Tech Solutions Pvt. Ltd.",
                "category": "Tech & Electronics",
                "business_types": ["Product-based", "Physical Location", "Service / Digital"],
                "primary_business_type": "Service / Digital",
                "sub_category": "Software Development",
                "city": "Jaipur, India",
                "logo_url": "https://sevenunique.com/logo.png",
                "tagline": "Website Design Partner For Modern Businesses",
                "target_audience": "Startups, enterprises, and growing businesses",
                "differentiators": ["3500+ successfully delivered projects", "ISO certified technology provider"],
                "products_services": ["Web Development", "Mobile App Development", "Custom Software Development"]
            },
            "brand_preferences": {
                "tagline": "Trusted Website Design Partner For Modern Businesses",
                "brand_colors": ["#FFFFFF", "#000000", "#FF5722", "#212121", "#121212"],
                "tones": ["Modern", "Professional", "Youthful", "Bold"],
                "default_language": "English",
                "target_audience_summary": "Startups, enterprises, and growing businesses globally",
                "services_products_summary": ["Web Development", "Mobile App Development", "AI Development Services"]
            },
            "photos": [
                {"url": "https://sevenunique.com/img1.jpg", "alt": "Work environment", "type": "hero", "selected": True},
                {"url": "https://sevenunique.com/img2.jpg", "alt": "Team collaboration", "type": "product", "selected": False}
            ]
        },
        "selected_photo_urls": ["https://sevenunique.com/img1.jpg"],
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/onboarding/business-profile", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["job_id"] == job_id
        assert data["business_details"]["business_name"] == "SevenUnique Tech Solutions Pvt. Ltd."
        assert data["business_details"]["city"] == "Jaipur, India"
        assert data["business_details"]["primary_business_type"] == "Service / Digital"
        assert len(data["business_details"]["differentiators"]) == 2
        assert len(data["business_details"]["products_services"]) == 3
        assert len(data["brand_preferences"]["brand_colors"]) == 5
        assert "Modern" in data["brand_preferences"]["tones"]
        assert data["brand_preferences"]["default_language"] == "English"
        assert len(data["photos"]) == 2
        assert data["selected_photo_urls"] == ["https://sevenunique.com/img1.jpg"]


@pytest.mark.asyncio
async def test_update_business_details_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_edit_biz_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://sevenunique.com/",
        "status": "completed",
        "progress": 100,
        "current_step": "completed",
        "onboarding_step": "business_details",
        "step_statuses": {
            "fetching": "completed",
            "brand_voice": "completed",
            "colors": "completed",
            "category": "completed",
            "photos": "completed"
        },
        "results": {},
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.put(
            "/api/v1/onboarding/business-details",
            json={
                "business_name": "SevenUnique Tech Solutions Pvt. Ltd.",
                "category": "Tech & Electronics",
                "business_types": ["Product-based", "Physical Location", "Service / Digital"],
                "primary_business_type": "Service / Digital",
                "sub_category": "Software Development",
                "city": "Jaipur, India",
                "logo_url": "https://sevenunique.com/logo-updated.png",
                "tagline": "Website Design Partner For Modern Businesses",
                "target_audience": "Startups, enterprises, and growing businesses",
                "differentiators": [
                    "3500+ successfully delivered projects across various global industries",
                    "Government recognized and ISO certified technology solutions provider",
                    "Specialized in scalable fintech, ecommerce, and AI solutions",
                    "Experienced team of 375+ expert members and developers"
                ],
                "products_services": [
                    "Web Development",
                    "Mobile App Development",
                    "Custom Software Development",
                    "AI Development Services",
                    "UI/UX Design",
                    "QA Testing Automation",
                    "Fintech & Payment Solutions"
                ]
            },
            headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["business_details"]["business_name"] == "SevenUnique Tech Solutions Pvt. Ltd."
        assert len(data["business_details"]["differentiators"]) == 4
        assert len(data["business_details"]["products_services"]) == 7
        assert data["onboarding_step"] == "brand_preferences"

    # Verify persistence in MongoDB collections
    job_doc = await db["website_analysis_jobs"].find_one({"job_id": job_id})
    assert job_doc["onboarding_step"] == "brand_preferences"
    assert job_doc["results"]["business_details"]["logo_url"] == "https://sevenunique.com/logo-updated.png"

    bus_doc = await db["businesses"].find_one({"owner_id": uid})
    assert bus_doc["name"] == "SevenUnique Tech Solutions Pvt. Ltd."
    assert bus_doc["city"] == "Jaipur, India"
    assert len(bus_doc["differentiators"]) == 4

    kit_doc = await db["brand_kits"].find_one({"owner_id": uid})
    assert kit_doc["brand_name"] == "SevenUnique Tech Solutions Pvt. Ltd."
    assert kit_doc["city"] == "Jaipur, India"


@pytest.mark.asyncio
async def test_update_brand_preferences_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_edit_pref_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://sevenunique.com/",
        "status": "completed",
        "progress": 100,
        "current_step": "completed",
        "onboarding_step": "brand_preferences",
        "step_statuses": {
            "fetching": "completed",
            "brand_voice": "completed",
            "colors": "completed",
            "category": "completed",
            "photos": "completed"
        },
        "results": {},
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.put(
            "/api/v1/onboarding/brand-preferences",
            json={
                "tagline": "Trusted Website Design Partner For Modern Businesses",
                "brand_colors": ["#FFFFFF", "#0A0A0A", "#E65100", "#1E1E1E", "#000000"],
                "tones": ["Modern", "Trendy", "Youthful", "Bold", "Professional"],
                "default_language": "English",
                "target_audience_summary": "Startups, enterprises, and growing businesses globally",
                "services_products_summary": [
                    "Web Development",
                    "Mobile App Development",
                    "Custom Software Development",
                    "AI Development Services",
                    "UI/UX Design"
                ]
            },
            headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["brand_preferences"]["brand_colors"]) == 5
        assert data["brand_preferences"]["brand_colors"][2] == "#E65100"
        assert "Modern" in data["brand_preferences"]["tones"]
        assert data["brand_preferences"]["default_language"] == "English"
        assert data["onboarding_step"] == "website_photos"

    # Verify persistence
    job_doc = await db["website_analysis_jobs"].find_one({"job_id": job_id})
    assert job_doc["onboarding_step"] == "website_photos"

    bus_doc = await db["businesses"].find_one({"owner_id": uid})
    assert bus_doc["brand_colors"] == ["#FFFFFF", "#0A0A0A", "#E65100", "#1E1E1E", "#000000"]
    assert "Modern" in bus_doc["tones"]
    assert bus_doc["preferred_language"] == "English"


@pytest.mark.asyncio
async def test_get_and_save_website_photos_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_photos_{uid[:8]}"
    now = datetime.now(timezone.utc)
    test_photos = [
        {"url": f"https://example.com/photo_{i}.jpg", "alt": f"Photo {i}", "type": "product", "selected": False}
        for i in range(1, 6)
    ]
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://example.com/",
        "status": "completed",
        "progress": 100,
        "current_step": "completed",
        "onboarding_step": "website_photos",
        "step_statuses": {"photos": "completed"},
        "results": {"photos": test_photos},
        "selected_photo_urls": ["https://example.com/photo_1.jpg", "https://example.com/photo_2.jpg"],
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. GET photos
        resp_get = await ac.get("/api/v1/onboarding/website-photos", headers=headers)
        assert resp_get.status_code == 200
        get_data = resp_get.json()
        assert get_data["success"] is True
        assert len(get_data["photos"]) == 5
        assert get_data["selected_count"] == 2
        assert get_data["max_selection_limit"] == 10

        # 2. POST chosen photos
        new_selection = [
            "https://example.com/photo_1.jpg",
            "https://example.com/photo_3.jpg",
            "https://example.com/photo_4.jpg"
        ]
        resp_save = await ac.post(
            "/api/v1/onboarding/website-photos",
            json={"selected_photo_urls": new_selection},
            headers=headers
        )
        assert resp_save.status_code == 200
        save_data = resp_save.json()
        assert save_data["selected_count"] == 3
        assert save_data["selected_photo_urls"] == new_selection


@pytest.mark.asyncio
async def test_save_website_photos_max_limit_enforced(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_limit_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://example.com/",
        "status": "completed",
        "results": {"photos": []},
        "selected_photo_urls": [],
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        too_many = [f"https://example.com/pic_{i}.jpg" for i in range(11)]
        resp = await ac.post(
            "/api/v1/onboarding/website-photos",
            json={"selected_photo_urls": too_many},
            headers=headers
        )
        assert resp.status_code == 400
        assert "maximum of 10 photos" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_website_photo_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_upload_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://example.com/",
        "status": "completed",
        "results": {"photos": []},
        "selected_photo_urls": [],
        "created_at": now,
        "updated_at": now
    })

    # Create a real small PNG in memory
    import io
    from PIL import Image
    img_byte_arr = io.BytesIO()
    img = Image.new("RGB", (120, 120), color=(73, 109, 137))
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/onboarding/website-photos/upload",
            files={"file": ("storefront.png", img_bytes, "image/png")},
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "user_upload"
        assert data["width"] == 120
        assert data["height"] == 120
        assert data["selected"] is True
        assert "storefront" in data["alt"].lower()
        assert "/uploads/onboarding_photos/" in data["url"]

    # Verify added to job
    job_doc = await db["website_analysis_jobs"].find_one({"job_id": job_id})
    assert len(job_doc["results"]["photos"]) == 1
    assert data["url"] in job_doc["selected_photo_urls"]


@pytest.mark.asyncio
async def test_complete_website_onboarding_flow(auth_user):
    headers, uid = auth_user
    db = get_database()

    job_id = f"job_complete_{uid[:8]}"
    now = datetime.now(timezone.utc)
    await db["website_analysis_jobs"].insert_one({
        "job_id": job_id,
        "user_id": uid,
        "onboarding_type": "website",
        "url": "https://sevenunique.com/",
        "status": "completed",
        "onboarding_step": "website_photos",
        "results": {},
        "created_at": now,
        "updated_at": now
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/onboarding/website-onboarding/complete", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["job_id"] == job_id
        assert data["next_step"] == "social_connectivity"
        assert data["onboarding_route"] == "/onboarding?step=social_connectivity"

    # Verify user collection stepped forward to step 3
    user_doc = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user_doc["onboarding_step"] == 3
    assert user_doc["online_presence"] == "website"


@pytest.mark.asyncio
async def test_ai_website_analysis_endpoint_dynamic_photos():
    """
    Tests that POST /api/v1/ai/website-analysis dynamically extracts real photos and metadata
    from entered website HTML without hardcoded mock placeholders.
    """
    sample_rich_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dynamic Artisan Bakery</title>
        <meta name="description" content="Handcrafted organic breads and pastries.">
        <meta property="og:image" content="https://bakery.test/images/hero-artisan.jpg">
    </head>
    <body>
        <h1>Artisan Bakery Studio</h1>
        <p>Fresh sourdough, croissants, and artisan loaves baked fresh every morning.</p>
        <img src="/static/logo-bakery.png" class="brand-logo" alt="Artisan Logo">
        <img src="/static/sourdough-loaf.jpg" alt="Rustic Sourdough" srcset="/static/sourdough-loaf.jpg 1x, /static/sourdough-loaf-2x.jpg 2x">
        <picture>
            <source srcset="/static/croissant-banner.webp">
            <img src="/static/croissant-banner.jpg" alt="Butter Croissants">
        </picture>
        <div style="background-image: url('/static/kitchen-oven.jpg');"></div>
    </body>
    </html>
    """

    with patch.object(WebsiteAnalysisService, "_fetch_website", return_value=(sample_rich_html, "https://example.com/", None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/ai/website-analysis", json={"website_url": "https://example.com/"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            res_data = data["data"]
            assert res_data["business_name"] != ""
            assert len(res_data["photos"]) >= 4
            assert any("hero-artisan.jpg" in p for p in res_data["photos"])
            assert any("sourdough-loaf" in p for p in res_data["photos"])
            assert any("croissant-banner" in p for p in res_data["photos"])
            assert any("kitchen-oven.jpg" in p for p in res_data["photos"])
            assert res_data["status"] == "completed"

