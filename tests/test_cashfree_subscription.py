import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from app.main import app
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.core.security import create_access_token
from app.services.cashfree_service import CashfreeService

def test_cashfree_return_url_uses_generated_subscription_id():
    subscription_id = "SUB_2CBCBB0D9D73"

    return_url = CashfreeService._build_return_url(
        "http://localhost:3000/payment/success?order_id={subscription_id}&sub_id={subscription_id}",
        subscription_id,
    )

    assert return_url == (
        "http://localhost:3000/payment/success"
        f"?order_id={subscription_id}&sub_id={subscription_id}"
    )
    assert "{" not in return_url

@pytest.fixture(autouse=True)
async def setup_test_user():
    connect_to_mongo()
    db = get_database()
    user = await db["users"].find_one({"email": "subscriber@example.com"})
    if not user:
        insert_res = await db["users"].insert_one({
            "name": "Cashfree Subscriber",
            "email": "subscriber@example.com",
            "phone_number": "9876543210",
            "role": "user",
            "current_plan": "FREE",
            "plan_id": "FREE",
            "created_at": datetime.now(timezone.utc)
        })
        user_id = str(insert_res.inserted_id)
    else:
        user_id = str(user["_id"])

    token = create_access_token(user_id)
    yield {"user_id": user_id, "token": token, "db": db}

@pytest.mark.asyncio
async def test_create_and_verify_cashfree_subscription(setup_test_user):
    user_info = setup_test_user
    token = user_info["token"]
    headers = {"Authorization": f"Bearer {token}"}
    db = user_info["db"]

    # 1. Test POST /api/v1/payments/subscription/create
    mock_cf_res = {
        "success": True,
        "subscription_id": "SUB_TEST12345678",
        "order_id": "SUB_TEST12345678",
        "cf_subscription_id": "CF_SUB_888999",
        "subscription_session_id": "sub_session_mock_123",
        "payment_url": "https://payments-test.cashfree.com/subs-checkout/checkout/mock_token",
        "status": "INITIALIZED",
        "auth_amount": 799.0,
        "recurring_amount": 799.0,
        "amount": 799.0,
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "billing_cycle": "monthly",
        "currency": "INR"
    }

    with patch("app.services.cashfree_service.CashfreeService.create_subscription", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_cf_res

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.post(
                "/api/v1/payments/subscription/create",
                json={
                    "plan_id": "STARTER",
                    "billing_cycle": "monthly",
                    "customer_phone": "9876543210"
                },
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["subscription_id"] == "SUB_TEST12345678"
            assert data["payment_url"] == "https://payments-test.cashfree.com/subs-checkout/checkout/mock_token"
            assert data["auth_amount"] == 799.0
            assert data["recurring_amount"] == 799.0

    # 2. Test GET /api/v1/payments/subscription/status/{subscription_id}
    mock_status_res = {
        "subscription_id": "SUB_TEST12345678",
        "order_id": "SUB_TEST12345678",
        "cf_subscription_id": "CF_SUB_888999",
        "status": "ACTIVE",
        "auth_amount": 799.0,
        "recurring_amount": 799.0,
        "amount": 799.0,
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "billing_cycle": "monthly",
        "customer_email": "subscriber@example.com",
        "auth_status": "SUCCESS",
        "next_schedule_date": "2026-11-30",
        "verified": True,
        "message": "Subscription is active"
    }

    with patch("app.services.cashfree_service.CashfreeService.get_subscription_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = mock_status_res

        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.get(
                "/api/v1/payments/subscription/status/SUB_TEST12345678",
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["subscription_id"] == "SUB_TEST12345678"
            assert data["status"] == "ACTIVE"
            assert data["verified"] is True
            assert data["recurring_amount"] == 799.0

    # 3. Test POST /api/v1/payments/subscription/verify
    with patch("app.services.cashfree_service.CashfreeService.get_subscription_status", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_status_res

        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.post(
                "/api/v1/payments/subscription/verify",
                json={"subscription_id": "SUB_TEST12345678"},
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["verified"] is True
            assert data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_cashfree_status_changed_webhook_activates_plan_once(setup_test_user):
    user_info = setup_test_user
    db = user_info["db"]
    user_id = user_info["user_id"]
    subscription_id = f"SUB_WEBHOOK_{user_id[-8:]}"

    await db["payment_subscriptions"].insert_one({
        "user_id": user_id,
        "subscription_id": subscription_id,
        "cf_subscription_id": "CF_SUB_WEBHOOK",
        "plan_id": "STARTER",
        "billing_cycle": "monthly",
        "auth_amount": 942.82,
        "recurring_amount": 942.82,
        "status": "INITIALIZED",
    })
    await db["payment_transactions"].insert_one({
        "user_id": user_id,
        "subscription_id": subscription_id,
        "order_id": subscription_id,
        "plan_id": "STARTER",
        "status": "pending",
        "amount": 942.82,
    })

    payload = {
        "type": "SUBSCRIPTION_STATUS_CHANGED",
        "data": {
            "subscription_details": {
                "subscription_id": subscription_id,
                "cf_subscription_id": "CF_SUB_WEBHOOK",
                "subscription_status": "ACTIVE",
            },
            "authorization_details": {"authorization_status": "SUCCESS"},
        },
    }

    result = await CashfreeService.process_webhook(db, payload)
    assert result["success"] is True

    sub = await db["subscriptions"].find_one({"user_id": user_id})
    assert sub["plan_id"] == "STARTER"
    assert sub["credits_remaining"] == 350
    tx_count = await db["credit_transactions"].count_documents({
        "user_id": user_id,
        "reference_id": subscription_id,
    })
    assert tx_count == 2

    await CashfreeService.process_webhook(db, payload)
    sub_after_retry = await db["subscriptions"].find_one({"user_id": user_id})
    assert sub_after_retry["credits_remaining"] == 350
    assert await db["credit_transactions"].count_documents({
        "user_id": user_id,
        "reference_id": subscription_id,
    }) == 2
