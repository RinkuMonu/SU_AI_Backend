import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.services.subscription_service import SubscriptionService
from app.services.payin_service import PayinService

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    settings.PAYIN_URL = "http://mock.finuniques.in/payin"
    settings.PAYIN_TOKEN = "mock_token"
    yield
    close_mongo_connection()

async def create_clean_test_user(db, name: str = "Test User"):
    user_id = ObjectId()
    email = f"test_{user_id}@dhandagrow.test"
    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": f"+919{str(user_id)[-9:]}",
        "hashed_password": get_password_hash("TestPass@123"),
        "role": "businessman",
        "email_verified": True,
        "phone_verified": True,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(user_doc)
    # Initialize free subscription
    await SubscriptionService.get_or_create_subscription(db, str(user_id))
    token = create_access_token(subject=str(user_id))
    return str(user_id), token

original_post = AsyncClient.post

async def mock_finunique_create(self, url, *args, **kwargs):
    if "finuniques.in" in str(url) or "mock.finuniques.in" in str(url):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "success": True,
            "data": {
                "redirectURL": "upi://pay?pa=dhandagrow@icici&pn=DhandaGrow&am=1.00&cu=INR",
                "redirectEx": "https://gateway.finuniques.in/checkout/mock123",
                "reference": "MOCK_PROV_REF_12345",
                "qrCode": "upi://pay?pa=dhandagrow@icici&pn=DhandaGrow&am=1.00&cu=INR"
            }
        }
        return mock_res
    return await original_post(self, url, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Select the Plan and Generate QR
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_01_select_test_plan_and_generate_qr(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN", "billing_cycle": "monthly"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["order_id"].startswith("ORDER_")
        assert data["amount"] == 1.0
        assert data["currency"] == "INR"
        assert "upi://pay" in data["qr_code"]
        assert data["provider_reference"] == "MOCK_PROV_REF_12345"

        # Verify DB transaction record
        tx = await db["payment_transactions"].find_one({"order_id": data["order_id"]})
        assert tx is not None
        assert tx["user_id"] == user_id
        assert tx["plan_id"] == "TEST_PLAN"
        assert tx["status"] == "initiated"
        assert tx["purchased_credits"] == 20
        assert tx["amount"] == 1.0
        assert tx["qr_code"] == data["qr_code"]
        assert tx["provider_reference"] == "MOCK_PROV_REF_12345"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Check Pending Status
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_02_check_pending_status(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 2")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = create_res.json()["order_id"]

        status_res = await ac.get(
            f"/api/v1/payments/payin/status/{order_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert status_res.status_code == 200
        s_data = status_res.json()
        assert s_data["order_id"] == order_id
        assert s_data["status"] == "initiated"
        assert s_data["can_cancel"] is True
        assert s_data["amount"] == 1.0
        assert s_data["currency"] == "INR"
        assert s_data["plan_id"] == "TEST_PLAN"
        assert s_data["provider_reference"] == "MOCK_PROV_REF_12345"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Test Back Navigation and Cancellation
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_03_back_navigation_and_cancellation(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 3")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = create_res.json()["order_id"]

        # Cancel the pending payment
        cancel_res = await ac.post(
            "/api/v1/payments/payin/cancel",
            json={"order_id": order_id, "reason": "User clicked back button"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cancel_res.status_code == 200
        c_data = cancel_res.json()
        assert c_data["success"] is True
        assert c_data["status"] == "cancelled"
        assert c_data["can_cancel"] is True

        # Check status again
        status_res = await ac.get(
            f"/api/v1/payments/payin/status/{order_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "cancelled"

        # Verify DB: user did not get upgraded, credits unchanged
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "FREE"
        assert sub["credits_remaining"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# 4. Complete Payment and Verify Activation (Once)
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_04_payment_success_and_single_activation(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 4")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = create_res.json()["order_id"]

        # Simulate provider webhook callback
        callback_payload = {
            "orderId": order_id,
            "responseCode": "100",
            "amount": "100",  # In paise (100 paise = 1.0 INR)
            "pgTransId": "PG_FIN_TX_98765"
        }
        cb_res = await ac.post("/api/v1/payments/payin/callback", json=callback_payload)
        assert cb_res.status_code == 200
        assert cb_res.json()["success"] is True
        assert cb_res.json()["status"] == "success"

        # Verify DB transaction
        tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert tx["status"] == "success"
        assert tx["external_transaction_id"] == "PG_FIN_TX_98765"
        assert tx["verified_at"] is not None

        # Verify subscription was activated
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "TEST_PLAN"
        # 5 initial + 20 purchased = 25 credits
        assert sub["credits_remaining"] == 25
        assert sub["credits_total"] == 25


# ─────────────────────────────────────────────────────────────────────────────
# 5. Idempotency: Duplicate Callbacks / Retries
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_05_duplicate_callback_idempotency(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 5")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = create_res.json()["order_id"]

        callback_payload = {
            "orderId": order_id,
            "responseCode": "100",
            "amount": "1.00",
            "pgTransId": "PG_FIN_TX_IDEMP_1"
        }
        # First call
        res1 = await ac.post("/api/v1/payments/payin/callback", json=callback_payload)
        assert res1.status_code == 200
        assert res1.json()["success"] is True

        # Second call (webhook retry or duplicate network response)
        res2 = await ac.post("/api/v1/payments/payin/callback", json=callback_payload)
        assert res2.status_code == 200
        assert res2.json()["success"] is True
        assert res2.json()["message"] == "Already processed"

        # Third call (browser refresh / verify endpoint)
        res3 = await ac.post(f"/api/v1/payments/payin/verify/{order_id}", headers={"Authorization": f"Bearer {token}"})
        assert res3.status_code == 200
        assert res3.json()["verified"] is True

        # Ensure NO double-credit grants: still exactly 25
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["credits_remaining"] == 25


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cancellation Blocked on Confirmed Payment
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_06_cannot_cancel_confirmed_payment(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 6")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        create_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = create_res.json()["order_id"]

        # Complete payment
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_id, "responseCode": "100", "amount": "1.0"}
        )

        # Attempt to cancel
        cancel_res = await ac.post(
            "/api/v1/payments/payin/cancel",
            json={"order_id": order_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert cancel_res.status_code == 200
        data = cancel_res.json()
        assert data["can_cancel"] is False
        assert data["status"] == "success"
        assert "Cancellation not allowed" in data["message"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Authenticated User-Scoped Transaction Report API
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_07_transaction_report_api(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 7")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create and cancel order 1
        res1 = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order1 = res1.json()["order_id"]
        await ac.post(
            "/api/v1/payments/payin/cancel",
            json={"order_id": order1, "reason": "Test cancel"},
            headers={"Authorization": f"Bearer {token}"}
        )

        # 2. Create and complete order 2
        res2 = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order2 = res2.json()["order_id"]
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order2, "responseCode": "100", "amount": "1.0", "pgTransId": "PG_TX_REPORT_1"}
        )

        # Fetch transaction report
        report_res = await ac.get(
            "/api/v1/payments/transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert report_res.status_code == 200
        report = report_res.json()
        assert report["success"] is True
        assert report["total"] >= 2
        assert len(report["data"]) >= 2

        # Check required fields
        item = report["data"][0]
        assert "order_id" in item
        assert "provider_reference" in item
        assert "plan_name" in item
        assert "plan_id" in item
        assert "amount" in item
        assert "currency" in item
        assert "status" in item
        assert "created_at" in item
        assert "purchased_credits" in item
        assert item["purchased_credits"] == 20

        # Check status filter
        filter_res = await ac.get(
            "/api/v1/payments/transactions?status=cancelled",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert filter_res.status_code == 200
        filtered_items = filter_res.json()["data"]
        for it in filtered_items:
            assert it["status"] == "cancelled"

        # Check subscription endpoint alias
        alias_res = await ac.get(
            "/api/v1/subscription/transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert alias_res.status_code == 200
        assert alias_res.json()["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. AI Credit Report and Ledger Separate from Payment History
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_08_ai_credit_report_and_ledger(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create and complete ₹1 payment
        res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_id = res.json()["order_id"]
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_id, "responseCode": "100", "amount": "1.0"}
        )

        # Check credit summary
        summary_res = await ac.get(
            "/api/v1/subscription/credits/summary",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert summary_res.status_code == 200
        s_data = summary_res.json()["data"]
        assert s_data["plan_id"] == "TEST_PLAN"
        assert s_data["credits_remaining"] == 25

        # Check credit transactions
        ledger_res = await ac.get(
            "/api/v1/subscription/credits/transactions",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert ledger_res.status_code == 200
        ledger = ledger_res.json()["data"]
        assert len(ledger) >= 1
        # Check credit grant entry
        credit_entry = [entry for entry in ledger if entry.get("transaction_type") == "grant" or entry.get("amount") == 20]
        assert len(credit_entry) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 9. Test Plan Reset and Repeatable Flow
# ─────────────────────────────────────────────────────────────────────────────
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create)
async def test_09_test_plan_reset_and_flow_repeat(mock_post):
    db = get_database()
    user_id, token = await create_clean_test_user(db, name="Lifecycle User 9")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Complete initial ₹1 payment
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        order_1 = c_res.json()["order_id"]
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_1, "responseCode": "100", "amount": "1.0"}
        )

        # Confirm user is active on TEST_PLAN
        me_res1 = await ac.get("/api/v1/subscription/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res1.json()["data"]["plan_id"] == "TEST_PLAN"

        # 2. Reset the test plan
        reset_res = await ac.post(
            "/api/v1/payments/test-plan/reset",
            json={"confirm": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert reset_res.status_code == 200
        r_data = reset_res.json()
        assert r_data["success"] is True
        assert r_data["previous_plan"] == "TEST_PLAN"
        assert r_data["new_plan"] == "FREE"
        assert r_data["credits_available"] == 5
        assert order_1 in r_data["preserved_paid_orders"]

        # Confirm DB subscription is FREE
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "FREE"
        assert sub["credits_remaining"] == 5

        # Confirm the genuine paid order was PRESERVED in payment_transactions (audit trail)
        paid_tx = await db["payment_transactions"].find_one({"order_id": order_1})
        assert paid_tx["status"] == "success"

        # 3. Repeat payment flow from clean state
        repeat_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "TEST_PLAN"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert repeat_res.status_code == 200
        order_2 = repeat_res.json()["order_id"]
        assert order_2 != order_1

        # Complete second payment
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_2, "responseCode": "100", "amount": "1.0"}
        )

        # Confirm active again with clean credits (5 + 20 = 25)
        me_res2 = await ac.get("/api/v1/subscription/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res2.json()["data"]["plan_id"] == "TEST_PLAN"
        assert me_res2.json()["data"]["credits_remaining"] == 25
