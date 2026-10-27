import asyncio
from datetime import datetime, timezone
import io
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from PIL import Image

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token, get_password_hash
from app.services.google_maps_onboarding_service import GoogleMapsOnboardingService
from app.schemas.google_maps_onboarding import (
    GoogleMapsSearchRequest,
    GoogleMapsUrlResolveRequest,
    GoogleMapsPlaceItem,
    GoogleMapsSearchResponse,
    GoogleMapsResolveResponse,
    SelectGoogleMapsBusinessRequest,
    GoogleMapsWebsiteRequest,
    GoogleMapsCategoryRequest,
    GoogleMapsProfileRequest,
    SelectGoogleMapsPhotosRequest,
)


@pytest.fixture(autouse=True)
def ensure_db():
    connect_to_mongo()


@pytest.fixture
async def auth_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Maps Tester",
        "email": f"mapstest_{str(uid)[-6:]}@onboarding-test.com",
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
        "name": "Maps Tester 2",
        "email": f"mapstest2_{str(uid)[-6:]}@onboarding-test.com",
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


def create_dummy_image_bytes(format="PNG", size=(100, 100), color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# 1. Google Maps Search & Place Details Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_google_maps_places_success(auth_user):
    headers, uid = auth_user
    mock_places_api_response = {
        "places": [
            {
                "id": "ChIJ_TEST_PLACE_123",
                "displayName": {"text": "Cafe De Flora"},
                "formattedAddress": "123 MI Road, Jaipur, Rajasthan 302001, India",
                "location": {"latitude": 26.9124, "longitude": 75.7873},
                "rating": 4.6,
                "userRatingCount": 350,
                "websiteUri": "https://cafedeflora.example.com",
                "nationalPhoneNumber": "+91 141 2345678",
                "types": ["cafe", "restaurant", "food"],
                "photos": [
                    {"name": "places/ChIJ_TEST_PLACE_123/photos/photo_ref_1"}
                ],
                "googleMapsUri": "https://maps.google.com/?cid=123"
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_places_api_response
        mock_post.return_value = mock_resp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/onboarding/google-maps/search?query=Cafe+De+Flora", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 1
            place = data["places"][0]
            assert place["place_id"] == "ChIJ_TEST_PLACE_123"
            assert place["business_name"] == "Cafe De Flora"
            assert place["rating"] == 4.6
            assert place["review_count"] == 350
            assert place["website"] == "https://cafedeflora.example.com"
            assert len(place["photos"]) == 1
            # Verify proxy photo URL does not expose Google Maps API key
            assert "key=" not in place["photos"][0]
            assert "/api/v1/onboarding/google-maps/photo" in place["photos"][0]


@pytest.mark.asyncio
async def test_search_google_maps_empty_results(auth_user):
    headers, uid = auth_user
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"places": []}
        mock_post.return_value = mock_resp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/onboarding/google-maps/search?query=NonExistentBusinessXYZ123456", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["total"] == 0
            assert data["places"] == []


@pytest.mark.asyncio
async def test_search_google_maps_query_too_short(auth_user):
    headers, uid = auth_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onboarding/google-maps/search?query=a", headers=headers)
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_search_google_maps_provider_error_handling(auth_user):
    headers, uid = auth_user
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "RESOURCE_EXHAUSTED"
        mock_post.return_value = mock_resp

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/onboarding/google-maps/search?query=Test+Bakery", headers=headers)
            assert resp.status_code == 429
            assert "rate limit" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_place_details_success(auth_user):
    headers, uid = auth_user
    mock_place = GoogleMapsPlaceItem(
        place_id="ChIJ_DETAIL_456",
        business_name="Apex Salon & Spa",
        formatted_address="45 Park Avenue, Mumbai, Maharashtra 400001, India",
        latitude=18.922,
        longitude=72.834,
        rating=4.8,
        review_count=512,
        website="https://apexsalon.example.com",
        types=["beauty_salon", "spa"]
    )

    with patch.object(GoogleMapsOnboardingService, "get_place_details", return_value=mock_place):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/onboarding/google-maps/place/ChIJ_DETAIL_456", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["place_id"] == "ChIJ_DETAIL_456"
            assert data["business_name"] == "Apex Salon & Spa"
            assert data["rating"] == 4.8


# -----------------------------------------------------------------------------
# 2. Google Maps URL Resolution Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_maps_url_invalid_domain(auth_user):
    headers, uid = auth_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/onboarding/google-maps/resolve-url",
            json={"url": "https://phishing-site.com/fake-maps"},
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "not a recognized Google Maps link" in data["message"]


@pytest.mark.asyncio
async def test_resolve_maps_url_valid_place_url(auth_user):
    headers, uid = auth_user
    mock_resolved = GoogleMapsResolveResponse(
        success=True,
        message="Business successfully resolved from Google Maps link.",
        place=GoogleMapsPlaceItem(
            place_id="ChIJ_ROYAL_JEWEL",
            business_name="Royal Jewellers",
            formatted_address="Johari Bazaar, Jaipur, Rajasthan 302003, India",
            latitude=26.920,
            longitude=75.825,
            rating=4.9,
            review_count=890,
            types=["jewelry_store"]
        ),
        resolved_query="Royal Jewellers"
    )

    with patch.object(GoogleMapsOnboardingService, "resolve_maps_url", return_value=mock_resolved):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/onboarding/google-maps/resolve-url",
                json={"url": "https://www.google.com/maps/place/Royal+Jewellers/@26.920,75.825,17z"},
                headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["place"]["place_id"] == "ChIJ_ROYAL_JEWEL"
            assert data["place"]["business_name"] == "Royal Jewellers"


# -----------------------------------------------------------------------------
# 3. Selected Business Persistence Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_google_maps_business(auth_user):
    headers, uid = auth_user
    db = get_database()

    payload = {
        "place_id": "ChIJ_SU_STORE_001",
        "business_name": "Modern Living Home Furnishings",
        "formatted_address": "88 Ring Road, Jaipur, Rajasthan 302015, India",
        "latitude": 26.850,
        "longitude": 75.780,
        "rating": 4.7,
        "review_count": 210,
        "website": "https://modernliving.example.com",
        "phone_number": "+91 141 9988776",
        "city": "Jaipur",
        "state": "Rajasthan",
        "country": "India",
        "postal_code": "302015",
        "types": ["home_goods_store", "furniture_store"],
        "photos": ["https://backend.example.com/api/v1/onboarding/google-maps/photo?photo_name=sample_p1"]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/onboarding/google-maps/select",
            json=payload,
            headers=headers
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["success"] is True
        assert state["current_step"] == "website"
        assert state["onboarding_step_number"] == 2
        assert state["selected_business"]["place_id"] == "ChIJ_SU_STORE_001"
        assert state["selected_business"]["business_name"] == "Modern Living Home Furnishings"

    # Verify database persistence across collections
    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus is not None
    assert bus["google_maps_place_id"] == "ChIJ_SU_STORE_001"
    assert bus["business_name"] == "Modern Living Home Furnishings"
    assert bus["online_presence"] == "google_maps"
    assert bus["rating"] == 4.7

    kit = await db["brand_kits"].find_one({"$or": [{"owner_id": uid}, {"user_id": uid}]})
    assert kit is not None
    assert kit["brand_name"] == "Modern Living Home Furnishings"

    user = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user["online_presence"] == "google_maps"
    assert user["onboarding_step"] == 2


# -----------------------------------------------------------------------------
# 4. Website Step (Save / Skip) Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_website_step(auth_user):
    headers, uid = auth_user
    db = get_database()

    # Pre-select business
    await db["google_maps_onboarding_jobs"].insert_one({
        "user_id": uid,
        "place_id": "ChIJ_TEST_1",
        "current_step": "website",
        "onboarding_step_number": 2
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Save valid website
        resp = await client.put(
            "/api/v1/onboarding/google-maps/website",
            json={"website_url": "dhandagrow.in", "skip": False},
            headers=headers
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["current_step"] == "category"
        assert state["onboarding_step_number"] == 3
        assert state["website"] == "https://dhandagrow.in/"
        assert state["website_skipped"] is False

    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus is not None
    assert bus["website"] == "https://dhandagrow.in/"


@pytest.mark.asyncio
async def test_skip_website_step(auth_user):
    headers, uid = auth_user
    db = get_database()

    await db["businesses"].insert_one({"owner_id": uid, "website": "https://preexisting.com"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Skip website
        resp = await client.put(
            "/api/v1/onboarding/google-maps/website",
            json={"website_url": None, "skip": True},
            headers=headers
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["current_step"] == "category"
        assert state["website_skipped"] is True
        # Verify pre-existing website was NOT overwritten
        bus = await db["businesses"].find_one({"owner_id": uid})
        assert bus["website"] == "https://preexisting.com"


# -----------------------------------------------------------------------------
# 5. Category & Subcategory Taxonomy Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_categories_and_search(auth_user):
    headers, uid = auth_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Full categories list
        resp = await client.get("/api/v1/onboarding/categories", headers=headers)
        assert resp.status_code == 200
        cats = resp.json()["data"]
        cat_ids = [c["id"] for c in cats]
        assert "salon_spa" in cat_ids
        assert "home_living" in cat_ids
        assert "restaurant_cafe" in cat_ids
        assert "education_coaching" in cat_ids

        # Category search
        resp_search = await client.get("/api/v1/onboarding/categories?q=furniture", headers=headers)
        assert resp_search.status_code == 200
        search_data = resp_search.json()["data"]
        assert len(search_data) > 0
        assert any(c["id"] == "home_living" for c in search_data)

        # Subcategories lookup
        resp_sub = await client.get("/api/v1/onboarding/subcategories?category_id=home_living", headers=headers)
        assert resp_sub.status_code == 200
        sub_data = resp_sub.json()["data"]
        sub_names = [s["subcategory_name"] for s in sub_data]
        assert "Bathroom Fittings" in sub_names
        assert "Furniture" in sub_names
        assert "Home Decor" in sub_names


@pytest.mark.asyncio
async def test_save_category_step(auth_user):
    headers, uid = auth_user
    db = get_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/onboarding/google-maps/category",
            json={"category": "Home & Living", "sub_category": "Furniture"},
            headers=headers
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["current_step"] == "profile"
        assert state["onboarding_step_number"] == 4
        assert state["category"] == "Home & Living"
        assert state["sub_category"] == "Furniture"

    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus is not None
    assert bus["category"] == "Home & Living"
    assert bus["sub_category"] == "Furniture"


# -----------------------------------------------------------------------------
# 6. Business Profile Details Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_profile_details_required_and_partial_updates(auth_user):
    headers, uid = auth_user
    db = get_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing promotion goal should fail
        resp_fail = await client.put(
            "/api/v1/onboarding/google-maps/profile",
            json={"business_name": "Jaipur Furnishings", "promotion_goal": ""},
            headers=headers
        )
        assert resp_fail.status_code in (400, 422)

        # Successful initial submission
        resp = await client.put(
            "/api/v1/onboarding/google-maps/profile",
            json={
                "business_name": "Jaipur Furnishings",
                "promotion_goal": "Custom solid teak wood dining sets and luxury sofas",
                "target_audience": "New homeowners and interior designers",
                "differentiators": ["100% Solid Teak", "10-Year Warranty", "Free Assembly"]
            },
            headers=headers
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["current_step"] == "photos"
        assert state["onboarding_step_number"] == 5
        assert state["profile"]["business_name"] == "Jaipur Furnishings"
        assert state["profile"]["target_audience"] == "New homeowners and interior designers"

        # Partial update: update business_name without erasing differentiators
        resp_part = await client.put(
            "/api/v1/onboarding/google-maps/profile",
            json={
                "business_name": "Jaipur Royal Furnishings",
                "promotion_goal": "Custom solid teak wood dining sets and luxury sofas"
            },
            headers=headers
        )
        assert resp_part.status_code == 200
        state_part = resp_part.json()
        assert state_part["profile"]["business_name"] == "Jaipur Royal Furnishings"
        assert state_part["profile"]["target_audience"] == "New homeowners and interior designers"
        assert "100% Solid Teak" in state_part["profile"]["differentiators"]


# -----------------------------------------------------------------------------
# 7. Logo and Business Photo Uploads & Limit Enforcement Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logo_upload_and_removal(auth_user):
    headers, uid = auth_user
    db = get_database()

    logo_bytes = create_dummy_image_bytes(format="PNG", size=(200, 200), color=(10, 100, 200))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Upload valid logo
        files = {"file": ("brand_logo.png", logo_bytes, "image/png")}
        resp = await client.post("/api/v1/onboarding/google-maps/logo/upload", files=files, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        logo_url = data["logo_url"]
        assert "/uploads/business_logos/logo_" in logo_url

        bus = await db["businesses"].find_one({"owner_id": uid})
        assert bus is not None
        assert bus["logo_url"] == logo_url

        # 2. Corrupted file upload fails
        corrupt_files = {"file": ("bad_logo.png", b"not-an-image-data-string", "image/png")}
        resp_bad = await client.post("/api/v1/onboarding/google-maps/logo/upload", files=corrupt_files, headers=headers)
        assert resp_bad.status_code == 400

        # 3. Remove logo
        resp_del = await client.delete("/api/v1/onboarding/google-maps/logo", headers=headers)
        assert resp_del.status_code == 200
        bus_after = await db["businesses"].find_one({"owner_id": uid})
        assert bus_after.get("logo_url") is None


@pytest.mark.asyncio
async def test_photo_upload_selection_and_15_limit(auth_user):
    headers, uid = auth_user
    db = get_database()

    photo_bytes = create_dummy_image_bytes(format="JPEG", size=(300, 300), color=(0, 150, 50))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Upload business photo
        files = {"file": ("storefront.jpg", photo_bytes, "image/jpeg")}
        resp_up = await client.post("/api/v1/onboarding/google-maps/photos/upload", files=files, headers=headers)
        assert resp_up.status_code == 200
        photo = resp_up.json()
        assert photo["type"] == "user_upload"
        uploaded_url = photo["url"]

        # 2. Get photos gallery
        resp_gal = await client.get("/api/v1/onboarding/google-maps/photos", headers=headers)
        assert resp_gal.status_code == 200
        gal = resp_gal.json()
        assert gal["max_selection_limit"] == 15
        assert uploaded_url in [p["url"] for p in gal["photos"]]

        # 3. Select 16 photos should fail (limit is 15)
        excessive_urls = [f"https://example.com/photo_{i}.jpg" for i in range(16)]
        resp_limit = await client.post(
            "/api/v1/onboarding/google-maps/photos/select",
            json={"selected_photo_urls": excessive_urls},
            headers=headers
        )
        assert resp_limit.status_code == 400
        assert "maximum of 15" in resp_limit.json()["detail"]

        # 4. Select valid count (<= 15)
        valid_urls = [f"https://example.com/photo_{i}.jpg" for i in range(5)]
        resp_sel = await client.post(
            "/api/v1/onboarding/google-maps/photos/select",
            json={"selected_photo_urls": valid_urls},
            headers=headers
        )
        assert resp_sel.status_code == 200
        assert resp_sel.json()["selected_count"] == 5

        # 5. Remove photo
        resp_rem = await client.delete(
            f"/api/v1/onboarding/google-maps/photos?photo_url={uploaded_url}",
            headers=headers
        )
        assert resp_rem.status_code == 200
        assert uploaded_url not in [p["url"] for p in resp_rem.json()["photos"]]


# -----------------------------------------------------------------------------
# 8. State Resumption, Completion & Cross-User Security Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_state_resumption_after_refresh(auth_user):
    headers, uid = auth_user
    db = get_database()

    # Seed job session
    await db["google_maps_onboarding_jobs"].insert_one({
        "user_id": uid,
        "place_id": "ChIJ_SAVED_101",
        "current_step": "profile",
        "onboarding_step_number": 4,
        "category": "Salon & Spa",
        "sub_category": "Hair Treatments",
        "selected_business": {
            "place_id": "ChIJ_SAVED_101",
            "business_name": "Glow Luxury Salon",
            "formatted_address": "MG Road, Bengaluru, Karnataka 560001, India",
            "rating": 4.9
        }
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onboarding/google-maps/state", headers=headers)
        assert resp.status_code == 200
        state = resp.json()
        assert state["success"] is True
        assert state["current_step"] == "profile"
        assert state["onboarding_step_number"] == 4
        assert state["category"] == "Salon & Spa"
        assert state["selected_business"]["business_name"] == "Glow Luxury Salon"


@pytest.mark.asyncio
async def test_complete_onboarding_validation_and_step_transition(auth_user):
    headers, uid = auth_user
    db = get_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Incomplete state fails
        resp_fail = await client.post("/api/v1/onboarding/google-maps/complete", headers=headers)
        assert resp_fail.status_code == 400

        # Seed completed prerequisites
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": uid},
            {"$set": {
                "user_id": uid,
                "place_id": "ChIJ_FINAL_999",
                "category": "Restaurant & Cafe",
                "selected_business": {
                    "place_id": "ChIJ_FINAL_999",
                    "business_name": "Brew & Bistro",
                    "formatted_address": "12 Park Lane, Pune, Maharashtra 411001, India"
                },
                "profile": {
                    "business_name": "Brew & Bistro",
                    "promotion_goal": "Handcrafted artisanal coffees and European breakfast brunch"
                }
            }},
            upsert=True
        )

        # 2. Finalize completion
        resp_comp = await client.post("/api/v1/onboarding/google-maps/complete", headers=headers)
        assert resp_comp.status_code == 200
        comp_data = resp_comp.json()
        assert comp_data["success"] is True
        assert comp_data["next_step"] == "social_connectivity"
        assert "social_connectivity" in comp_data["onboarding_route"]

    # Verify user stepper advanced to Step 3
    user_after = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user_after["onboarding_step"] == 3
    assert user_after["online_presence"] == "google_maps"


@pytest.mark.asyncio
async def test_cross_user_isolation(auth_user, auth_user2):
    headers1, uid1 = auth_user
    headers2, uid2 = auth_user2
    db = get_database()

    # User 1 sets up business
    await db["businesses"].insert_one({
        "owner_id": uid1,
        "name": "User 1 Business",
        "google_maps_place_id": "ChIJ_USER1_BUS"
    })
    await db["google_maps_onboarding_jobs"].insert_one({
        "user_id": uid1,
        "place_id": "ChIJ_USER1_BUS",
        "category": "Jewellery"
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 2 fetching their state should NOT see User 1's place
        resp2 = await client.get("/api/v1/onboarding/google-maps/state", headers=headers2)
        assert resp2.status_code == 200
        state2 = resp2.json()
        assert state2["selected_business"] is None or state2["selected_business"].get("place_id") != "ChIJ_USER1_BUS"
