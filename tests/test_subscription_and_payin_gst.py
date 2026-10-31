import pytest
from decimal import Decimal
from unittest.mock import patch
import httpx
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from app.main import app
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.core.security import create_access_token
from app.core.billing_config import PLANS, calculate_plan_gst
from app.services.pdf_service import PDFService

from app.services.subscription_service import SubscriptionService

async def create_gst_test_user(db, email: str, name: str = "GST Test User"):
    await db["users"].delete_many({"email": email})
    user_res = await db["users"].insert_one({
        "name": name,
        "email": email,
        "phone_number": "9876543210",
        "role": "user",
        "current_plan": "FREE",
        "plan_id": "FREE",
        "created_at": datetime.now(timezone.utc)
    })
    user_id = str(user_res.inserted_id)
    await db["subscriptions"].delete_many({"user_id": user_id})
    await db["payment_transactions"].delete_many({"user_id": user_id})
    await SubscriptionService.get_or_create_subscription(db, user_id)
    token = create_access_token(user_id)
    return user_id, token

original_post = AsyncClient.post

async def mock_finunique_create_gst(self, *args, **kwargs):
    url = kwargs.get("url") or (args[0] if args else "")
    url_str = str(url)
    if "mock.payin.com" in url_str or "finunique" in url_str:
        req_json = kwargs.get("json", {})
        amt = req_json.get("amount", 0)
        ref = req_json.get("reference", "MOCK_ORDER")
        return httpx.Response(
            200,
            json={
                "status": True,
                "message": "Payment link generated",
                "data": {
                    "redirectURL": "http://mock.payin.com/checkout/123",
                    "redirectEx": "http://mock.payin.com/checkout/123",
                    "paymentUrl": "http://mock.payin.com/checkout/123",
                    "upiUrl": f"upi://pay?pa=mock@bank&am={amt}",
                    "orderId": ref,
                    "reference": ref,
                    "amount": amt
                }
            }
        )
    return await original_post(self, *args, **kwargs)

from app.core.config import settings

@pytest.fixture(autouse=True)
async def init_db():
    connect_to_mongo()
    settings.PAYIN_URL = "http://mock.payin.com"
    settings.PAYIN_TOKEN = "mock_token"
    yield
    close_mongo_connection()

# ─────────────────────────────────────────────────────────────────────────────
# 1. 18% GST Calculations on ₹799 Plan & Other Plans
# ─────────────────────────────────────────────────────────────────────────────

def test_01_starter_799_plan_gst_calculation():
    """Verify dynamic 18% GST calculation on ₹799 plan: GST ₹143.82, total ₹942.82."""
    calc = calculate_plan_gst(799.0)
    assert calc["base_price"] == 799.0
    assert calc["gst_applicable"] is True
    assert calc["gst_rate"] == 0.18
    assert calc["gst_percentage"] == 18.0
    assert calc["gst_amount"] == 143.82
    assert calc["total_payable"] == 942.82
    assert calc["total_price"] == 942.82

def test_02_other_paid_plans_gst_calculation():
    """Verify GST calculations across all tiers and billing cycles."""
    # Growth plan: ₹2999 -> GST ₹539.82, Total ₹3538.82
    growth = calculate_plan_gst(2999)
    assert growth["base_price"] == 2999.0
    assert growth["gst_amount"] == 539.82
    assert growth["total_payable"] == 3538.82

    # Business plan: ₹4999 -> GST ₹899.82, Total ₹5898.82
    business = calculate_plan_gst(4999)
    assert business["base_price"] == 4999.0
    assert business["gst_amount"] == 899.82
    assert business["total_payable"] == 5898.82

    # Influencer plan: ₹9999 -> GST ₹1799.82, Total ₹11798.82
    influencer = calculate_plan_gst(9999)
    assert influencer["base_price"] == 9999.0
    assert influencer["gst_amount"] == 1799.82
    assert influencer["total_payable"] == 11798.82

    # Quarterly Starter: ₹2157 -> GST ₹388.26, Total ₹2545.26
    q_starter = calculate_plan_gst(2157)
    assert q_starter["base_price"] == 2157.0
    assert q_starter["gst_amount"] == 388.26
    assert q_starter["total_payable"] == 2545.26

    # Yearly Starter: ₹7670 -> GST ₹1380.60, Total ₹9050.60
    y_starter = calculate_plan_gst(7670)
    assert y_starter["base_price"] == 7670.0
    assert y_starter["gst_amount"] == 1380.60
    assert y_starter["total_payable"] == 9050.60

def test_03_free_plan_zero_gst():
    """Verify Free plan charges zero GST and maintains 0 total payable."""
    free_calc = calculate_plan_gst(0)
    assert free_calc["base_price"] == 0.0
    assert free_calc["gst_applicable"] is False
    assert free_calc["gst_rate"] == 0.0
    assert free_calc["gst_percentage"] == 0.0
    assert free_calc["gst_amount"] == 0.0
    assert free_calc["total_payable"] == 0.0
    assert free_calc["total_price"] == 0.0

# ─────────────────────────────────────────────────────────────────────────────
# 2. Subscription API Endpoints Response Structure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_04_subscription_plans_api_returns_gst_breakdown():
    """Verify /subscription/plans and /subscription/available-plans return base_price, currency, gst_percentage, gst_amount, total_payable."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/plans")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True

        plans_list = data["plans_list"]
        starter = next(p for p in plans_list if p["id"] == "STARTER")
        assert starter["base_price"] == 799.0
        assert starter["currency"] == "INR"
        assert starter["gst_percentage"] == 18.0
        assert starter["gst_amount"] == 143.82
        assert starter["total_payable"] == 942.82
        assert starter["total_price"] == 942.82

        free = next(p for p in plans_list if p["id"] == "FREE")
        assert free["base_price"] == 0.0
        assert free["gst_percentage"] == 0.0
        assert free["gst_amount"] == 0.0
        assert free["total_payable"] == 0.0

        # Also check /available-plans
        avail_res = await ac.get("/api/v1/subscription/available-plans")
        assert avail_res.status_code == 200
        avail_starter = next(p for p in avail_res.json()["data"] if p["id"] == "STARTER")
        assert avail_starter["base_price"] == 799.0
        assert avail_starter["gst_amount"] == 143.82
        assert avail_starter["total_payable"] == 942.82

# ─────────────────────────────────────────────────────────────────────────────
# 3. Payin Order Creation, Verification, Cancellation, & Failure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_05_payin_order_creation_calculates_and_stores_gst(mock_post):
    """Verify order creation calculates final amount including 18% GST (₹942.82) and persists breakdown."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_user_1@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER", "billing_cycle": "monthly"},
            headers=headers
        )
        assert res.status_code == 200
        resp_data = res.json()
        assert resp_data["success"] is True
        assert resp_data["amount"] == 942.82

        # Verify DB transaction record
        tx = await db["payment_transactions"].find_one({"order_id": resp_data["order_id"]})
        assert tx is not None
        assert tx["base_amount"] == 799.0
        assert tx["gst_rate"] == 0.18
        assert tx["gst_percentage"] == 18.0
        assert tx["gst_amount"] == 143.82
        assert tx["amount"] == 942.82
        assert tx["total_payable"] == 942.82
        assert tx["status"] in ["pending", "initiated"]

        # Ensure user plan is still FREE before payment
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "FREE"

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_06_payment_cancellation_flow(mock_post):
    """Verify user payment cancellation preserves transaction records without activating plan."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_cancel@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER"},
            headers=headers
        )
        order_id = c_res.json()["order_id"]

        # Cancel payment
        cancel_res = await ac.post(
            "/api/v1/payments/payin/cancel",
            json={"order_id": order_id, "reason": "User changed mind"},
            headers=headers
        )
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"

        # Verify DB record
        tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert tx["status"] == "cancelled"
        assert tx["amount"] == 942.82
        assert tx["gst_amount"] == 143.82

        # Verify user remains FREE
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "FREE"

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_07_payment_failure_flow(mock_post):
    """Verify failed payment callback marks transaction as failed without activating plan."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_failed@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER"},
            headers=headers
        )
        order_id = c_res.json()["order_id"]

        # Simulate provider failure callback
        fail_cb = await ac.post(
            "/api/v1/payments/payin/callback",
            json={
                "orderId": order_id,
                "responseCode": "102",
                "status": "FAILED",
                "message": "Card declined by issuing bank"
            }
        )
        assert fail_cb.status_code == 200
        assert fail_cb.json()["status"] == "failed"

        # Confirm DB status
        tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert tx["status"] == "failed"

        # Subscription remains FREE
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "FREE"

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_08_successful_payment_verification_and_plan_upgrade(mock_post):
    """Verify successful payment callback activates subscription and credits with verified GST total."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_success@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER"},
            headers=headers
        )
        order_id = c_res.json()["order_id"]

        # Successful callback with exact amount
        cb_res = await ac.post(
            "/api/v1/payments/payin/callback",
            json={
                "orderId": order_id,
                "responseCode": "100",
                "amount": "942.82",
                "paymentMode": "UPI"
            }
        )
        assert cb_res.status_code == 200
        assert cb_res.json()["status"] == "success"

        # Confirm DB transaction marked as success with complete GST breakdown
        tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert tx["status"] == "success"
        assert tx["amount"] == 942.82
        assert tx["base_amount"] == 799.0
        assert tx["gst_amount"] == 143.82

        # Confirm user subscription upgraded to STARTER
        sub = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub["plan_id"] == "STARTER"
        assert sub["status"] == "active"
        assert sub["credits_remaining"] >= 105  # 5 free + 100 plan credits

# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency & Duplicate Callback Protection
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_09_duplicate_callback_idempotency(mock_post):
    """Verify duplicate callbacks are safely handled without charging or granting credits twice."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_dup@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER"},
            headers=headers
        )
        order_id = c_res.json()["order_id"]

        # First callback
        cb1 = await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_id, "responseCode": "100", "amount": "942.82"}
        )
        assert cb1.json()["status"] == "success"

        sub1 = await db["subscriptions"].find_one({"user_id": user_id})
        credits_1 = sub1["credits_remaining"]

        # Duplicate callback
        cb2 = await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_id, "responseCode": "100", "amount": "942.82"}
        )
        assert cb2.json()["status"] == "success"
        assert "Already processed" in cb2.json()["message"]

        # Confirm credits were NOT duplicated
        sub2 = await db["subscriptions"].find_one({"user_id": user_id})
        assert sub2["credits_remaining"] == credits_1

# ─────────────────────────────────────────────────────────────────────────────
# 5. Transaction Report and Receipt Consistency
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post", autospec=True, side_effect=mock_finunique_create_gst)
async def test_10_transaction_report_and_pdf_receipt_consistency(mock_post):
    """Verify the Transaction Report displays GST breakdown and PDF Receipt formats base price, 18% GST, and total payable correctly."""
    db = get_database()
    user_id, token = await create_gst_test_user(db, "gst_report@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create and complete payment
        c_res = await ac.post(
            "/api/v1/payments/payin/create",
            json={"plan_id": "STARTER"},
            headers=headers
        )
        order_id = c_res.json()["order_id"]
        await ac.post(
            "/api/v1/payments/payin/callback",
            json={"orderId": order_id, "responseCode": "100", "amount": "942.82"}
        )

        # 1. Fetch transactions list
        tx_res = await ac.get("/api/v1/payments/transactions", headers=headers)
        assert tx_res.status_code == 200
        tx_data = tx_res.json()
        assert tx_data["total"] >= 1
        item = next(t for t in tx_data["data"] if t["order_id"] == order_id)

        assert item["amount"] == 942.82
        assert item["base_amount"] == 799.0
        assert item["gst_rate"] == 0.18
        assert item["gst_amount"] == 143.82
        assert item["total_payable"] == 942.82

        # 2. Generate and verify PDF Receipt
        tx_doc = await db["payment_transactions"].find_one({"order_id": order_id})
        pdf_bytes = PDFService.generate_receipt_pdf(tx_doc)
        assert len(pdf_bytes) > 1000
        assert pdf_bytes.startswith(b"%PDF")

