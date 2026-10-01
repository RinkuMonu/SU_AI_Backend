import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_database
from app.services.payin_service import PayinService
from app.core.config import settings
from unittest.mock import patch, MagicMock
from app.core.security import get_password_hash
import json

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def setup_db_and_user():
    from app.core.database import connect_to_mongo, close_mongo_connection
    connect_to_mongo()
    db = get_database()
    
    user = await db["users"].find_one({"email": "payment@example.com"})
    if not user:
        await db["users"].insert_one({
            "name": "Payment User",
            "email": "payment@example.com",
            "hashed_password": get_password_hash("Password@123"),
            "role": "user",
            "email_verified": True
        })
        
    settings.PAYIN_URL = "http://mock.payin.com"
    settings.PAYIN_TOKEN = "mock_token"
    
    yield
    close_mongo_connection()

from app.core.security import create_access_token
from datetime import timedelta

async def get_token():
    db = get_database()
    user = await db["users"].find_one({"email": "payment@example.com"})
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=str(user["_id"]), expires_delta=access_token_expires
    )
    return token

@pytest.mark.skipif(settings.ENVIRONMENT == "development", reason="Dev mode allows unauth")
async def test_create_payment_unauthenticated():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "STARTER"})
        assert res.status_code == 401

async def test_create_payment_free_plan():
    token = await get_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/create", 
            json={"plan_id": "FREE"}, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 400

async def test_create_payment_invalid_plan():
    token = await get_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/create", 
            json={"plan_id": "UNKNOWN"}, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 400

import httpx

original_post = httpx.AsyncClient.post

async def mock_post_success(self, url, *args, **kwargs):
    if "finuniques.in" in str(url) or "mock.payin.com" in str(url) or "test" in str(url):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"success": True, "data": {"redirectURL": "http://finunique.test/pay"}}
        return mock_res
    return await original_post(self, url, *args, **kwargs)

@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_post_success)
async def test_create_payment_success(mock_post):
    token = await get_token()
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/create", 
            json={"plan_id": "STARTER"}, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "order_id" in data
        assert data["payment_url"] == "http://finunique.test/pay"
        
        # Verify db
        db = get_database()
        tx = await db["payment_transactions"].find_one({"order_id": data["order_id"]})
        assert tx is not None
        assert tx["amount"] == 499.0 # 499 INR

async def mock_post_fail(self, url, *args, **kwargs):
    if "finuniques.in" in str(url) or "mock.payin.com" in str(url) or "test" in str(url):
        mock_res = MagicMock()
        mock_res.status_code = 500
        return mock_res
    return await original_post(self, url, *args, **kwargs)

@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_post_fail)
async def test_create_payment_api_failure(mock_post):
    token = await get_token()
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/create", 
            json={"plan_id": "STARTER"}, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 502

async def test_callback_success():
    # Setup order
    db = get_database()
    order_id = "ORDER_TEST_SUCCESS"
    await db["payment_transactions"].insert_one({
        "user_id": "some_user",
        "plan_id": "STARTER",
        "amount": 499.0,
        "order_id": order_id,
        "status": "initiated"
    })
    
    payload = {
        "orderId": order_id,
        "responseCode": "100",
        "amount": "49900",
        "pgTransId": "TX123"
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/callback", json=payload)
        assert res.status_code == 200
        assert res.json().get("success") is True
        
        # Verify idempotency
        res2 = await ac.post("/api/v1/payments/payin/callback", json=payload)
        assert res2.status_code == 200
        assert res2.json()["message"] == "Already processed"

async def test_callback_amount_mismatch():
    db = get_database()
    order_id = "ORDER_TEST_MISMATCH"
    await db["payment_transactions"].insert_one({
        "user_id": "some_user",
        "plan_id": "STARTER",
        "amount": 499.0,
        "order_id": order_id,
        "status": "initiated"
    })
    
    payload = {
        "orderId": order_id,
        "responseCode": "100",
        "amount": "1000",
        "pgTransId": "TX123"
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/payments/payin/callback", json=payload)
        assert res.status_code == 200
        assert res.json()["success"] is False
        assert res.json()["message"] == "Amount mismatch"

@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_post_success)
async def test_payment_status(mock_post):
    token = await get_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create
        res = await ac.post("/api/v1/payments/payin/create", 
            json={"plan_id": "PRO"}, headers={"Authorization": f"Bearer {token}"})
        order_id = res.json()["order_id"]
        
        # Check status
        status_res = await ac.get(f"/api/v1/payments/payin/status/{order_id}", headers={"Authorization": f"Bearer {token}"})
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "initiated"
