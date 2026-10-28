import uuid
import random
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.utils.url_validator import is_safe_url, is_safe_redirect_target, normalize_url
from app.services.website_analysis_service import WebsiteAnalysisService
from app.services.facebook_service import FacebookService
from app.services.linkedin_service import LinkedInService
from app.services.instagram_service import InstagramService

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


_phone_counter = 5000

async def create_test_user(db, role: str = "businessman", name: str = "Brand Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    phone_suffix = f"{random.randint(10000000, 99999999)}{_phone_counter % 10}"
    phone = f"+919{phone_suffix}"

    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": phone,
        "hashed_password": get_password_hash("TestPass@123"),
        "role": role,
        "phone_verified": True,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["users"].insert_one(user_doc)
    token = create_access_token(subject=str(user_id))
    return str(user_id), token, user_doc


# ─────────────────────────────────────────────────────────────────────────────
# 1. Website URL Analysis: Complete, Partial, and Missing Metadata (No Hallucinations)
# ─────────────────────────────────────────────────────────────────────────────
async def test_website_analysis_full_metadata():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Zenith Wellness & Spa — Authentic Ayurvedic Healing</title>
        <meta name="description" content="Premium holistic wellness and traditional spa treatments in Bengaluru.">
        <meta property="og:site_name" content="Zenith Wellness">
        <meta property="og:title" content="Zenith Wellness & Spa">
        <meta property="og:description" content="Experience peace and natural wellness.">
        <meta property="og:logo" content="https://zenithwellness.in/assets/logo.png">
        <link rel="icon" href="/favicon.ico">
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "HealthAndBeautyBusiness",
            "name": "Zenith Wellness",
            "slogan": "Holistic Healing, Natural Living"
        }
        </script>
        <style>
            :root {
                --primary: #2d5a27;
                --accent: #8fb9a8;
            }
            body { background-color: #f7f9f6; }
        </style>
    </head>
    <body>
        <header><h1>Welcome to Zenith Wellness</h1></header>
        <p>Contact: +91 98765 43210 | info@zenithwellness.in | 100 Feet Rd, Indiranagar, Bengaluru</p>
    </body>
    </html>
    """

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html_content
    mock_response.headers = {"content-type": "text/html"}

    db = get_database()
    with patch.object(WebsiteAnalysisService, "_fetch_website", new=AsyncMock(return_value=(html_content, "https://zenithwellness.in/", None))), \
         patch.object(WebsiteAnalysisService, "_execute_ai_analysis", new=AsyncMock(side_effect=lambda extracted, url: WebsiteAnalysisService._build_heuristic_fallback(extracted, url))):
        result = await WebsiteAnalysisService.analyze_website_direct(db, url="https://zenithwellness.in", allow_private_for_tests=True)

        assert result is not None
        # Verify dual keys for frontend Brand Kit schema
        assert result.get("brand_name") == "Zenith Wellness" or result.get("business_name") == "Zenith Wellness"
        assert (result.get("website") or "").rstrip("/") == "https://zenithwellness.in" or (result.get("website_url") or "").rstrip("/") == "https://zenithwellness.in"
        assert result.get("logo_url") == "https://zenithwellness.in/assets/logo.png"
        assert result.get("tagline") == "Holistic Healing, Natural Living"
        assert "Wellness" in str(result.get("business_category") or result.get("category"))
        # Verify brand colors were extracted and not fake neon defaults
        assert len(result.get("brand_colors", [])) > 0 or result.get("primary_color") is not None
        assert result.get("phone") == "+91 98765 43210"


async def test_website_analysis_partial_metadata_no_fabrication():
    """When metadata is minimal, authentic details are preserved without fabricating fake categories/colors."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sharma Book Store</title>
    </head>
    <body>
        <h1>Sharma Book Store</h1>
        <p>Old and new college textbooks.</p>
    </body>
    </html>
    """

    db = get_database()
    with patch.object(WebsiteAnalysisService, "_fetch_website", new=AsyncMock(return_value=(html_content, "https://sharmabooks.in/", None))), \
         patch.object(WebsiteAnalysisService, "_execute_ai_analysis", new=AsyncMock(side_effect=lambda extracted, url: WebsiteAnalysisService._build_heuristic_fallback(extracted, url))):
        result = await WebsiteAnalysisService.analyze_website_direct(db, url="https://sharmabooks.in", allow_private_for_tests=True)

        assert result is not None
        assert result.get("brand_name") == "Sharma Book Store" or result.get("business_name") == "Sharma Book Store"
        # Must not fabricate fake Technology & Digital Services
        assert result.get("business_category") != "Technology & Digital Services"
        # Must not fabricate fake slogan
        assert result.get("tagline") is None or result.get("tagline") == ""
        # Must not fabricate fake neon colors
        assert result.get("brand_colors") == [] or result.get("brand_colors") is None or len(result.get("brand_colors")) == 0


async def test_website_analysis_empty_metadata_graceful():
    """Empty HTML returns a valid partial structure without crashing."""
    html_content = "<html><body></body></html>"

    db = get_database()
    with patch.object(WebsiteAnalysisService, "_fetch_website", new=AsyncMock(return_value=(html_content, "https://empty-example.com/", None))), \
         patch.object(WebsiteAnalysisService, "_execute_ai_analysis", new=AsyncMock(side_effect=lambda extracted, url: WebsiteAnalysisService._build_heuristic_fallback(extracted, url))):
        result = await WebsiteAnalysisService.analyze_website_direct(db, url="https://empty-example.com", allow_private_for_tests=True)
        assert result is not None
        assert "brand_name" in result or "business_name" in result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Website Fetch Timeout and Error Handling
# ─────────────────────────────────────────────────────────────────────────────
async def test_website_analysis_timeout_handling():
    db = get_database()
    with patch.object(WebsiteAnalysisService, "_fetch_website", new=AsyncMock(return_value=(None, "https://slow-site.com/", "Request timed out after 15 seconds."))):
        result = await WebsiteAnalysisService.analyze_website_direct(db, url="https://slow-site.com", allow_private_for_tests=True)
        assert result is not None
        assert (result.get("website") or "").rstrip("/") == "https://slow-site.com" or (result.get("website_url") or "").rstrip("/") == "https://slow-site.com"


async def test_website_analysis_http_error_handling():
    db = get_database()
    with patch.object(WebsiteAnalysisService, "_fetch_website", new=AsyncMock(return_value=(None, "https://nonexistent-404.com/", "Website returned 404 Not Found."))):
        result = await WebsiteAnalysisService.analyze_website_direct(db, url="https://nonexistent-404.com", allow_private_for_tests=True)
        assert result is not None
        assert (result.get("website") or "").rstrip("/") == "https://nonexistent-404.com" or (result.get("website_url") or "").rstrip("/") == "https://nonexistent-404.com"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Safe URL Validation and SSRF Protections
# ─────────────────────────────────────────────────────────────────────────────
async def test_safe_url_validation():
    # Localhost and internal loopback addresses must be rejected
    assert not is_safe_url("http://localhost:8000")
    assert not is_safe_url("http://127.0.0.1:3000")
    assert not is_safe_url("http://127.0.0.1")
    assert not is_safe_url("http://0.0.0.0:80")
    
    # Cloud metadata service must be rejected
    assert not is_safe_url("http://169.254.169.254/latest/meta-data")
    assert not is_safe_url("http://169.254.169.254")

    # Private network ranges must be rejected
    assert not is_safe_url("http://10.0.0.1/admin")
    assert not is_safe_url("http://192.168.1.1/dashboard")
    assert not is_safe_url("http://172.16.0.1/internal")

    # Public destinations must be allowed
    assert is_safe_url("https://www.google.com")
    assert is_safe_url("https://github.com/torvalds/linux")
    assert is_safe_url("http://example.com")


async def test_safe_redirect_target_validation():
    safe_1, _, _ = is_safe_redirect_target("http://127.0.0.1:8000/api")
    assert not safe_1
    safe_2, _, _ = is_safe_redirect_target("http://localhost/secret")
    assert not safe_2
    safe_3, _, _ = is_safe_redirect_target("http://169.254.169.254/user-data")
    assert not safe_3
    safe_4, _, _ = is_safe_redirect_target("https://www.google.com/search")
    assert safe_4


# ─────────────────────────────────────────────────────────────────────────────
# 4. Brand Kit Save, Retrieve, and Partial Updates (Preserving Values)
# ─────────────────────────────────────────────────────────────────────────────
async def test_brand_kit_save_retrieve_and_partial_update():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Brand Owner")

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Initial save via POST /api/v1/brand
        initial_payload = {
            "business_name": "Royal Bakers",
            "business_category": "Bakery & Confectionery",
            "business_description": "Artisanal breads and cakes.",
            "tagline": "Baking fresh every morning",
            "primary_color": "#8b4513",
            "secondary_color": "#d2b48c",
            "brand_voice": "Friendly",
            "logo_url": "https://royalbakers.in/logo.png",
        }
        res_save = await ac.post("/api/v1/brand", json=initial_payload, headers=headers)
        assert res_save.status_code in (200, 201)
        data_save = res_save.json().get("data") or res_save.json()
        assert data_save.get("business_name") == "Royal Bakers"
        assert (data_save.get("primary_color") or "").upper() == "#8B4513"

        # 2. Retrieve via GET /api/v1/brand
        res_get = await ac.get("/api/v1/brand", headers=headers)
        assert res_get.status_code == 200
        data_get = res_get.json().get("data") or res_get.json()
        assert data_get.get("business_name") == "Royal Bakers"
        assert data_get.get("logo_url") == "https://royalbakers.in/logo.png"

        # 3. Partial update via PUT /api/v1/brand (updating tagline only)
        partial_update = {
            "tagline": "Pure Delights in Every Bite"
        }
        res_put = await ac.put("/api/v1/brand", json=partial_update, headers=headers)
        assert res_put.status_code == 200
        data_put = res_put.json().get("data") or res_put.json()
        assert data_put.get("tagline") == "Pure Delights in Every Bite"
        # Critical: business_name and logo_url must NOT be erased!
        assert data_put.get("business_name") == "Royal Bakers"
        assert data_put.get("logo_url") == "https://royalbakers.in/logo.png"
        assert (data_put.get("primary_color") or "").upper() == "#8B4513"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Google Maps Business Data Reuse in Brand Kit
# ─────────────────────────────────────────────────────────────────────────────
async def test_google_maps_business_data_reuse():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Gmaps Owner")

    # Seed business created from Google Maps flow
    await db["businesses"].insert_one({
        "owner_id": user_id,
        "name": "Gupta Medical Hall",
        "category": "Pharmacy",
        "location": "MG Road, Pune, Maharashtra",
        "phone": "+91 91234 56789",
        "website": "https://guptamedical.com",
        "business_description": "Trusted 24x7 community pharmacy offering genuine medicines.",
        "photos": ["https://maps.googleapis.com/maps/api/place/photo?ref=abc1234"],
        "created_at": datetime.now(timezone.utc),
    })

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Check autofill endpoint
        res_autofill = await ac.get("/api/v1/brand/autofill", headers=headers)
        assert res_autofill.status_code == 200
        autofill_data = res_autofill.json()
        assert autofill_data.get("success") is True
        data = autofill_data.get("data", {})
        assert data.get("business_name") == "Gupta Medical Hall"
        assert data.get("business_category") == "Pharmacy"
        assert data.get("phone") == "+91 91234 56789"
        assert data.get("website") == "https://guptamedical.com"
        # Generic business photo must NOT be set as official logo_url
        assert data.get("logo_url") is None or data.get("logo_url") == ""
        assert len(data.get("photos", [])) > 0

        # 2. Check that GET /api/v1/brand automatically presents autofilled draft when no brand_kit exists yet
        res_brand = await ac.get("/api/v1/brand", headers=headers)
        assert res_brand.status_code == 200
        brand_data = res_brand.json().get("data") or res_brand.json()
        assert brand_data.get("business_name") == "Gupta Medical Hall"
        assert brand_data.get("business_category") == "Pharmacy"

        # 3. Apply autofill explicitly
        res_apply = await ac.post("/api/v1/brand/autofill", headers=headers)
        assert res_apply.status_code == 200
        applied = res_apply.json().get("brand_kit", {})
        assert applied.get("business_name") == "Gupta Medical Hall"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Subscription Status and Plan/Billing Popup Eligibility Responses
# ─────────────────────────────────────────────────────────────────────────────
async def test_subscription_status_and_eligibility_responses():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Sub User")

    # User has not selected a plan yet
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # A. /api/v1/subscription/onboarding-status
        res_sub_onboarding = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res_sub_onboarding.status_code == 200
        sub_onboard_data = res_sub_onboarding.json()
        assert "requires_plan_selection" in sub_onboard_data
        assert "is_plan_required" in sub_onboard_data
        assert "is_eligible" in sub_onboard_data
        assert "should_show_modal" in sub_onboard_data
        assert "is_paid_plan" in sub_onboard_data
        # A new user without a paid transaction should not report paid plan
        assert sub_onboard_data.get("is_paid_plan") is False
        assert sub_onboard_data.get("requires_plan_selection") is True

        # B. /subscription/me
        res_sub_me = await ac.get("/subscription/me", headers=headers)
        assert res_sub_me.status_code == 200
        sub_me_data = res_sub_me.json()
        assert "requires_plan_selection" in sub_me_data
        assert "is_eligible" in sub_me_data
        assert "should_show_modal" in sub_me_data
        assert sub_me_data.get("is_paid_plan") is False

        # C. /api/v1/onboarding/status
        res_onboarding = await ac.get("/api/v1/onboarding/status", headers=headers)
        assert res_onboarding.status_code == 200
        onboarding_data = res_onboarding.json()
        assert "requires_plan_selection" in onboarding_data
        assert "is_plan_eligible" in onboarding_data
        assert "should_show_plan_modal" in onboarding_data
        assert onboarding_data.get("is_paid_plan") is False
        step_3 = onboarding_data.get("steps", {}).get("step_3_subscription_plan", {})
        assert step_3.get("requires_plan_selection") is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. Instagram Connection Regression Tests
# ─────────────────────────────────────────────────────────────────────────────
async def test_instagram_connection_status_and_disconnect():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Insta User")

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Instagram status before connecting
        res_status = await ac.get("/api/instagram/status", headers=headers)
        assert res_status.status_code == 200
        assert res_status.json().get("connected") is False

        # 2. Instagram connect endpoint
        res_connect = await ac.get("/api/instagram/connect", headers=headers)
        assert res_connect.status_code == 200
        assert "authorization_url" in res_connect.json()

        # 3. Instagram disconnect
        res_dis = await ac.post("/api/instagram/disconnect", headers=headers)
        assert res_dis.status_code == 200
        assert res_dis.json().get("success") is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Facebook and LinkedIn OAuth Flows (Accurate Configuration Reporting)
# ─────────────────────────────────────────────────────────────────────────────
async def test_facebook_unconfigured_reporting():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="FB User")

    headers = {"Authorization": f"Bearer {token}"}
    with patch.object(FacebookService, "is_configured", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Connect endpoint reports configured=False and does not issue fake connection
            res_connect = await ac.get("/api/facebook/connect", headers=headers)
            assert res_connect.status_code == 200
            fb_conn_data = res_connect.json()
            assert fb_conn_data.get("configured") is False
            assert fb_conn_data.get("authorization_url") is None

            # Status endpoint reports configured=False and connected=False
            res_status = await ac.get("/api/facebook/status", headers=headers)
            assert res_status.status_code == 200
            fb_status_data = res_status.json()
            assert fb_status_data.get("configured") is False
            assert fb_status_data.get("connected") is False


async def test_linkedin_unconfigured_reporting():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="LI User")

    headers = {"Authorization": f"Bearer {token}"}
    with patch.object(LinkedInService, "is_configured", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Connect endpoint reports configured=False and does not issue fake connection
            res_connect = await ac.get("/api/linkedin/connect", headers=headers)
            assert res_connect.status_code == 200
            li_conn_data = res_connect.json()
            assert li_conn_data.get("configured") is False
            assert li_conn_data.get("authorization_url") is None

            # Status endpoint reports configured=False and connected=False
            res_status = await ac.get("/api/linkedin/status", headers=headers)
            assert res_status.status_code == 200
            li_status_data = res_status.json()
            assert li_status_data.get("configured") is False
            assert li_status_data.get("connected") is False


async def test_social_platforms_overview_and_unified_endpoints():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Unified Social User")

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Overview endpoint
        res_platforms = await ac.get("/api/v1/social/platforms", headers=headers)
        assert res_platforms.status_code == 200
        platforms = res_platforms.json().get("platforms", {})
        assert "instagram" in platforms
        assert "facebook" in platforms
        assert "linkedin" in platforms
        for p in ["instagram", "facebook", "linkedin"]:
            assert "configured" in platforms[p]
            assert "connected" in platforms[p]

        # Unified connect route
        res_u_fb = await ac.get("/api/v1/social/connect/facebook", headers=headers)
        assert res_u_fb.status_code == 200

        # Unified status route
        res_u_li = await ac.get("/api/v1/social/status/linkedin", headers=headers)
        assert res_u_li.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 9. Unauthenticated and Unauthorized Requests
# ─────────────────────────────────────────────────────────────────────────────
async def test_unauthenticated_requests_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Brand Kit requires auth
        res_brand = await ac.get("/api/v1/brand")
        assert res_brand.status_code in (401, 403)

        # Brand Kit autofill requires auth
        res_autofill = await ac.get("/api/v1/brand/autofill")
        assert res_autofill.status_code in (401, 403)

        # Subscription onboarding-status requires auth
        res_sub = await ac.get("/api/v1/subscription/onboarding-status")
        assert res_sub.status_code in (401, 403)

        # Social platforms requires auth
        res_social = await ac.get("/api/v1/social/platforms")
        assert res_social.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# 10. Application Route Registration
# ─────────────────────────────────────────────────────────────────────────────
async def test_expected_routes_registered():
    route_paths = [r.path for r in app.routes]
    
    # Brand Kit routes
    assert "/api/v1/brand" in route_paths
    assert "/api/v1/brand/autofill" in route_paths
    assert "/api/v1/brand/analyze-website" in route_paths
    
    # Subscription routes
    assert "/api/v1/subscription/onboarding-status" in route_paths
    assert "/subscription/me" in route_paths
    assert "/api/v1/onboarding/status" in route_paths
    
    # Social routes
    assert "/api/v1/social/platforms" in route_paths
    assert "/api/v1/social/connect/{platform}" in route_paths
    assert "/api/v1/social/status/{platform}" in route_paths
    assert "/api/facebook/connect" in route_paths
    assert "/api/linkedin/connect" in route_paths
    assert "/api/instagram/connect" in route_paths
