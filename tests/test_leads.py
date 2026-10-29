import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


async def test_create_lead_success():
    db = get_database()
    payload = {
        "name": "Aakash Verma",
        "email": "aakash.verma@example.com",
        "subject": "Business Automation Inquiry",
        "message": "Hi, I am interested in AI content automation for my retail store in Jaipur.",
        "phone": "+919876543210",
        "source": "website_contact_form"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/leads", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert "lead_id" in data
        assert "Thank you" in data["message"]

        lead_id = data["lead_id"]
        lead_data = data["data"]
        assert lead_data["name"] == "Aakash Verma"
        assert lead_data["email"] == "aakash.verma@example.com"
        assert lead_data["subject"] == "Business Automation Inquiry"
        assert lead_data["phone"] == "+919876543210"
        assert lead_data["status"] == "new"

        # Verify direct MongoDB storage in "leads" collection
        doc = await db["leads"].find_one({"email": "aakash.verma@example.com"})
        assert doc is not None
        assert doc["name"] == "Aakash Verma"
        assert doc["email"] == "aakash.verma@example.com"
        assert doc["subject"] == "Business Automation Inquiry"
        assert "Hi, I am interested" in doc["message"]
        assert doc["status"] == "new"
        assert doc["source"] == "website_contact_form"
        assert "created_at" in doc

        # Cleanup
        await db["leads"].delete_one({"_id": doc["_id"]})


async def test_create_lead_via_contact_alias():
    db = get_database()
    payload = {
        "name": "Priya Sharma",
        "email": "priya.contact@example.com",
        "subject": "Social Media Reels Consultation",
        "message": "We need help scheduling our Instagram reels with AI."
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/contact", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        lead_id = data["lead_id"]

        # Confirm saved in database under "leads" collection
        doc = await db["leads"].find_one({"email": "priya.contact@example.com"})
        assert doc is not None
        assert doc["name"] == "Priya Sharma"

        # Cleanup
        await db["leads"].delete_one({"_id": doc["_id"]})


async def test_create_lead_validation_errors():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Missing name
        res1 = await ac.post("/api/v1/leads", json={
            "email": "valid@example.com",
            "subject": "Sub",
            "message": "Valid message here"
        })
        assert res1.status_code == 422

        # 2. Invalid email format
        res2 = await ac.post("/api/v1/leads", json={
            "name": "Test User",
            "email": "not-an-email",
            "subject": "Sub",
            "message": "Valid message here"
        })
        assert res2.status_code == 422

        # 3. Message too short (< 5 chars)
        res3 = await ac.post("/api/v1/leads", json={
            "name": "Test User",
            "email": "user@example.com",
            "subject": "Subject",
            "message": "Hi"
        })
        assert res3.status_code == 422


async def test_get_leads_and_pagination():
    db = get_database()
    # Insert test lead
    test_lead = {
        "name": "Listing Test Lead",
        "email": "list_test@example.com",
        "subject": "Listing Subject",
        "message": "Testing listing and pagination endpoint",
        "status": "new",
        "source": "website_contact_form"
    }
    insert_res = await db["leads"].insert_one(test_lead)
    lead_id = str(insert_res.inserted_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Get all leads
        res = await ac.get("/api/v1/leads?page=1&limit=10")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["total"] >= 1
        assert len(data["data"]) >= 1

        # Search filter
        search_res = await ac.get("/api/v1/leads?search=Listing%20Test")
        assert search_res.status_code == 200
        search_data = search_res.json()["data"]
        assert any(item["email"] == "list_test@example.com" for item in search_data)

        # Get single lead
        single_res = await ac.get(f"/api/v1/leads/{lead_id}")
        assert single_res.status_code == 200
        assert single_res.json()["name"] == "Listing Test Lead"

        # Update lead status
        patch_res = await ac.patch(f"/api/v1/leads/{lead_id}", json={
            "status": "contacted",
            "notes": "Spoke with client on phone, scheduled demo."
        })
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "contacted"
        assert patch_res.json()["notes"] == "Spoke with client on phone, scheduled demo."

        # Delete lead
        del_res = await ac.delete(f"/api/v1/leads/{lead_id}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

