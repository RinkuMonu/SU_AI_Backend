import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token, get_password_hash
from app.services.platform_onboarding_service import PlatformOnboardingService
from app.services.website_analysis_service import WebsiteAnalysisService
from app.schemas.website_analysis import WebsiteAnalysisJobResponse


@pytest.fixture(autouse=True)
def ensure_db():
    connect_to_mongo()


@pytest.fixture
async def auth_user():
    db = get_database()
    uid = ObjectId()
    doc = {
        "_id": uid,
        "name": "Platform Tester 1",
        "email": f"platform_{str(uid)[-6:]}@onboarding-test.com",
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
        "name": "Platform Tester 2",
        "email": f"platform2_{str(uid)[-6:]}@onboarding-test.com",
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


# -----------------------------------------------------------------------------
# 1. Catalog / Platform Options Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_platform_catalogs():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Marketplace catalog
        resp_m = await client.get("/api/v1/onboarding/platforms/catalog?onboarding_source=marketplace_seller")
        assert resp_m.status_code == 200
        data_m = resp_m.json()
        assert data_m["success"] is True
        assert data_m["onboarding_source"] == "marketplace_seller"
        m_ids = [p["id"] for p in data_m["platforms"]]
        assert "amazon" in m_ids
        assert "flipkart" in m_ids
        assert "meesho" in m_ids
        assert "other" in m_ids

        # 2. Wholesale / B2B catalog
        resp_b = await client.get("/api/v1/onboarding/platforms/catalog?onboarding_source=wholesale_b2b")
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["success"] is True
        assert data_b["onboarding_source"] == "wholesale_b2b"
        b_ids = [p["id"] for p in data_b["platforms"]]
        assert "indiamart" in b_ids
        assert "tradeindia" in b_ids
        assert "none_of_these" in b_ids
        assert any(p["is_none_option"] for p in data_b["platforms"] if p["id"] == "none_of_these")


# -----------------------------------------------------------------------------
# 2. Multiple Platform Selection & Persistence (Marketplace & Wholesale/B2B)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_multiple_marketplace_platforms(auth_user):
    headers, uid = auth_user
    db = get_database()

    payload = {
        "onboarding_source": "marketplace_seller",
        "selected_platforms": ["Amazon", "Flipkart", "Meesho", "amazon"]  # Case and duplicate test
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/onboarding/platforms", json=payload, headers=headers)
        assert resp.status_code == 200
        state = resp.json()
        assert state["success"] is True
        assert state["onboarding_source"] == "marketplace_seller"
        # Deduplicated and normalized
        assert state["selected_platforms"] == ["amazon", "flipkart", "meesho"]
        assert len(state["platform_details"]) == 3
        assert state["platform_details"][0]["name"] == "Amazon"
        assert state["platform_details"][1]["name"] == "Flipkart"
        assert state["platform_details"][2]["name"] == "Meesho"

    # Verify persistence in businesses collection
    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus is not None
    assert bus["online_presence"] == "marketplace_seller"
    assert bus["selected_platforms"] == ["amazon", "flipkart", "meesho"]

    # Verify user collection updated
    user = await db["users"].find_one({"_id": ObjectId(uid)})
    assert user["online_presence"] == "marketplace_seller"
    assert user["onboarding_step"] == 2


@pytest.mark.asyncio
async def test_save_wholesale_b2b_platforms(auth_user):
    headers, uid = auth_user
    db = get_database()

    payload = {
        "onboarding_source": "wholesale_b2b",
        "selected_platforms": ["indiamart", "TradeIndia", "justdial"]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/onboarding/wholesale-b2b/platforms", json=payload, headers=headers)
        assert resp.status_code == 200
        state = resp.json()
        assert state["success"] is True
        assert state["onboarding_source"] == "wholesale_b2b"
        assert state["selected_platforms"] == ["indiamart", "tradeindia", "justdial"]

    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus["online_presence"] == "wholesale_b2b"
    assert bus["selected_platforms"] == ["indiamart", "tradeindia", "justdial"]


# -----------------------------------------------------------------------------
# 3. Validation: 'Other' Custom Name & 'None of these' Mutual Exclusivity
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_other_platform_requires_custom_name(auth_user):
    headers, uid = auth_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing custom name should fail
        resp_fail = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["amazon", "other"],
                "custom_platform_name": None
            },
            headers=headers
        )
        assert resp_fail.status_code == 400
        assert "custom platform name" in resp_fail.json()["detail"].lower()

        # 2. Too short custom name should fail
        resp_short = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["other"],
                "custom_platform_name": " "
            },
            headers=headers
        )
        assert resp_short.status_code == 400

        # 3. Valid custom name succeeds
        resp_ok = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["other"],
                "custom_platform_name": "My Custom Marketplace"
            },
            headers=headers
        )
        assert resp_ok.status_code == 200
        state = resp_ok.json()
        assert state["custom_platform_name"] == "My Custom Marketplace"
        assert state["platform_details"][0]["name"] == "My Custom Marketplace"
        assert state["platform_details"][0]["is_custom"] is True


@pytest.mark.asyncio
async def test_none_of_these_mutual_exclusivity(auth_user):
    headers, uid = auth_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 'None of these' alone succeeds
        resp_ok = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "wholesale_b2b",
                "selected_platforms": ["none_of_these"]
            },
            headers=headers
        )
        assert resp_ok.status_code == 200
        state = resp_ok.json()
        assert state["none_of_these_selected"] is True
        assert state["selected_platforms"] == ["none_of_these"]

        # 2. 'None of these' combined with specific platforms must fail
        resp_conflict = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "wholesale_b2b",
                "selected_platforms": ["indiamart", "none_of_these"]
            },
            headers=headers
        )
        assert resp_conflict.status_code == 400
        assert "cannot select specific platforms" in resp_conflict.json()["detail"].lower()


# -----------------------------------------------------------------------------
# 4. Partial Updates & Field Preservation
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_saves_preserve_omitted_fields(auth_user):
    headers, uid = auth_user
    db = get_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Initial save with custom platform name
        await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["amazon", "other"],
                "custom_platform_name": "Craftsvilla Direct"
            },
            headers=headers
        )

        # 2. Update platform selection to ["amazon", "flipkart"] (omitting custom name)
        resp_part = await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["amazon", "flipkart"]
            },
            headers=headers
        )
        assert resp_part.status_code == 200
        state = resp_part.json()
        assert state["selected_platforms"] == ["amazon", "flipkart"]

        # 3. Submit storefront website without re-sending platforms
        resp_web = await client.post(
            "/api/v1/onboarding/platforms/website",
            json={"website_url": "https://craftsvilla.example.com", "skip": False},
            headers=headers
        )
        assert resp_web.status_code == 200
        web_data = resp_web.json()
        assert web_data["skipped"] is False
        assert web_data["website_url"] == "https://craftsvilla.example.com/"

        # Verify platform selections were NOT erased
        state_after = web_data["state"]
        assert state_after["selected_platforms"] == ["amazon", "flipkart"]
        assert state_after["onboarding_source"] == "marketplace_seller"

        bus = await db["businesses"].find_one({"owner_id": uid})
        assert bus["selected_platforms"] == ["amazon", "flipkart"]
        assert bus["website"] == "https://craftsvilla.example.com/"
        assert bus["online_presence"] == "marketplace_seller"


# -----------------------------------------------------------------------------
# 5. Website URL Analysis Reuse & Skip Path Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skip_website_manual_entry_path(auth_user):
    headers, uid = auth_user
    db = get_database()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Initial platform selection
        await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "wholesale_b2b",
                "selected_platforms": ["indiamart"]
            },
            headers=headers
        )

        # Skip website
        resp_skip = await client.post(
            "/api/v1/onboarding/platforms/website",
            json={"website_url": None, "skip": True},
            headers=headers
        )
        assert resp_skip.status_code == 200
        data = resp_skip.json()
        assert data["success"] is True
        assert data["skipped"] is True
        assert data["job_id"] is None
        assert data["state"]["website_skipped"] is True
        assert data["state"]["has_storefront"] is False

    bus = await db["businesses"].find_one({"owner_id": uid})
    assert bus["website_skipped"] is True
    assert bus["online_presence"] == "wholesale_b2b"


@pytest.mark.asyncio
async def test_reuse_existing_website_analysis_service(auth_user):
    headers, uid = auth_user
    mock_job_resp = WebsiteAnalysisJobResponse(
        success=True,
        job_id="job_mock_platform_123",
        url="https://mystore.example.com",
        status="pending",
        onboarding_type="marketplace_seller",
        created_at=datetime.now(timezone.utc)
    )

    with patch.object(WebsiteAnalysisService, "create_analysis_job", return_value=mock_job_resp) as mock_create:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/onboarding/platforms/website",
                json={"website_url": "https://mystore.example.com", "skip": False},
                headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["skipped"] is False
            assert data["job_id"] == "job_mock_platform_123"
            assert mock_create.called
            call_kwargs = mock_create.call_args[1]
            assert "mystore.example.com" in call_kwargs["payload"].url


# -----------------------------------------------------------------------------
# 6. Idempotence & Cross-User Security Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_platform_saves_no_duplicates(auth_user):
    headers, uid = auth_user
    db = get_database()

    payload = {
        "onboarding_source": "marketplace_seller",
        "selected_platforms": ["amazon", "flipkart"]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Submit twice
        resp1 = await client.post("/api/v1/onboarding/platforms", json=payload, headers=headers)
        resp2 = await client.post("/api/v1/onboarding/platforms", json=payload, headers=headers)
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    # Ensure single business document exists
    bus_count = await db["businesses"].count_documents({"owner_id": uid})
    assert bus_count == 1

    job_count = await db["platform_onboarding_jobs"].count_documents({"user_id": uid})
    assert job_count == 1


@pytest.mark.asyncio
async def test_cross_user_isolation(auth_user, auth_user2):
    headers1, uid1 = auth_user
    headers2, uid2 = auth_user2

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User 1 sets marketplace
        await client.post(
            "/api/v1/onboarding/platforms",
            json={
                "onboarding_source": "marketplace_seller",
                "selected_platforms": ["amazon", "myntra"]
            },
            headers=headers1
        )

        # User 2 gets their own state
        resp2 = await client.get("/api/v1/onboarding/platforms", headers=headers2)
        assert resp2.status_code == 200
        state2 = resp2.json()
        # User 2 must NOT see User 1's platforms
        assert state2["selected_platforms"] == []
