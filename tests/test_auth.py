
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_database, connect_to_mongo

@pytest.fixture(autouse=True)
async def setup_and_cleanup_db():
    connect_to_mongo()
    db = get_database()
    yield
    if db is not None:
        await db["users"].delete_many({"email": {"$regex": ".*@example\\.com|.*@test\\.com"}})
        await db["otps"].delete_many({"email": {"$regex": ".*@example\\.com|.*@test\\.com"}})
        await db["businesses"].delete_many({"userId": {"$exists": True}})
        await db["refresh_sessions"].delete_many({})

@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_signup_with_individual_fields(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "firstName": "Sejal",
        "lastName": "Gupta",
        "contactNumber": "+91 98765 43210",
        "email": "sejal_signup_test@example.com",
        "password": "Password123!",
        "otp": "123456",
        "accountType": "business",
        "termsAccepted": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    user = data["data"]["user"]
    assert user["firstName"] == "Sejal"
    assert user["lastName"] == "Gupta"
    assert user["fullName"] == "Sejal Gupta"
    assert user["contactNumber"] == "+91 98765 43210"
    assert user["email"] == "sejal_signup_test@example.com"
    assert user["emailVerified"] is True

@pytest.mark.asyncio
async def test_signup_with_full_name_backwards_compatible(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    assert res.status_code == 200
    assert res.json()["success"] is True

@pytest.mark.asyncio
async def test_duplicate_signup(async_client):
    req = {
        "firstName": "Test",
        "lastName": "Duplicate",
        "email": "dup@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    }
    await async_client.post("/api/v1/auth/signup", json=req)
    res = await async_client.post("/api/v1/auth/signup", json=req)
    assert res.status_code == 409

@pytest.mark.asyncio
async def test_login(async_client):
    await async_client.post("/api/v1/auth/signup", json={
        "firstName": "Login",
        "lastName": "User",
        "contactNumber": "9876543210",
        "email": "login_user@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    res = await async_client.post("/api/v1/auth/login", json={
        "email": "login_user@example.com",
        "password": "Password123"
    })
    assert res.status_code == 200
    assert "accessToken" in res.json()["data"]
    assert "set-cookie" in res.headers

