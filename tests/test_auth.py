
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_database

@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture(autouse=True)
async def cleanup_db():
    db = get_database()
    yield
    await db["users"].delete_many({})
    await db["businesses"].delete_many({})
    await db["refresh_sessions"].delete_many({})

@pytest.mark.asyncio
async def test_signup(async_client):
    res = await async_client.post("/api/v1/auth/signup", json={
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    assert res.status_code == 200
    assert res.json()["success"] == True

@pytest.mark.asyncio
async def test_duplicate_signup(async_client):
    req = {
        "fullName": "Test User",
        "email": "test@example.com",
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
        "fullName": "Test User",
        "email": "test@example.com",
        "password": "Password123",
        "accountType": "personal",
        "termsAccepted": True
    })
    res = await async_client.post("/api/v1/auth/login", json={
        "email": "test@example.com",
        "password": "Password123"
    })
    assert res.status_code == 200
    assert "accessToken" in res.json()["data"]
    assert "set-cookie" in res.headers
