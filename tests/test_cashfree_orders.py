import pytest
import hmac
import hashlib
import base64
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport, Response

from app.main import app
from app.core.config import settings
from app.core.database import connect_to_mongo, get_database
from app.core.security import create_access_token
from app.services.cashfree_service import CashfreeService
from app.core.billing_config import calculate_plan_gst, PLANS


class MockCashfreeClient:
    """Mock for httpx.AsyncClient used inside CashfreeService without affecting test ASGI client."""
    def __init__(self, post_res=None, get_res_map=None, get_default_res=None):
        self.post_res = post_res
        self.get_res_map = get_res_map or {}
        self.get_default_res = get_default_res

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def post(self, url, *args, **kwargs):
        if callable(self.post_res):
            return self.post_res(url, *args, **kwargs)
        return self.post_res or Response(200, json={})

    async def get(self, url, *args, **kwargs):
        for pattern, res in self.get_res_map.items():
            if pattern in url:
                if callable(res):
                    return res(url, *args, **kwargs)
                return res
        if self.get_default_res:
            return self.get_default_res
        return Response(404, json={"message": "Not found"})


@pytest.fixture(autouse=True)
async def setup_test_users():
    connect_to_mongo()
    db = get_database()
    
    # User A
    user_a = await db["users"].find_one({"email": "cashfree_user_a@example.com"})
    if not user_a:
        res_a = await db["users"].insert_one({
            "name": "Cashfree User A",
            "email": "cashfree_user_a@example.com",
            "phone_number": "9111111111",
            "role": "user",
            "current_plan": "FREE",
            "plan_id": "FREE",
            "created_at": datetime.now(timezone.utc)
        })
        user_a_id = str(res_a.inserted_id)
    else:
        user_a_id = str(user_a["_id"])

    # User B
    user_b = await db["users"].find_one({"email": "cashfree_user_b@example.com"})
    if not user_b:
        res_b = await db["users"].insert_one({
            "name": "Cashfree User B",
            "email": "cashfree_user_b@example.com",
            "phone_number": "9222222222",
            "role": "user",
            "current_plan": "FREE",
            "plan_id": "FREE",
            "created_at": datetime.now(timezone.utc)
        })
        user_b_id = str(res_b.inserted_id)
    else:
        user_b_id = str(user_b["_id"])

    # Clean up test artifacts for both users
    for uid in [user_a_id, user_b_id]:
        await db["credit_transactions"].delete_many({"user_id": uid})
        await db["subscription_history"].delete_many({"user_id": uid})
        await db["subscriptions"].delete_many({"user_id": uid})
        await db["payment_subscriptions"].delete_many({"user_id": uid})
        await db["payment_transactions"].delete_many({"user_id": uid})

    token_a = create_access_token(user_a_id)
    token_b = create_access_token(user_b_id)

    yield {
        "user_a_id": user_a_id,
        "token_a": token_a,
        "user_b_id": user_b_id,
        "token_b": token_b,
        "db": db
    }


def compute_valid_webhook_headers(raw_body: bytes) -> dict:
    """Generates valid Cashfree HMAC-SHA256 signature headers for testing."""
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    sig_data = f"{timestamp}".encode("utf-8") + raw_body
    computed = base64.b64encode(
        hmac.new(
            settings.CASHFREE_SECRET_KEY.encode("utf-8"),
            sig_data,
            hashlib.sha256
        ).digest()
    ).decode("utf-8")
    return {
        "x-webhook-timestamp": timestamp,
        "x-webhook-signature": computed,
        "Content-Type": "application/json"
    }


# ===========================================================================
# 1. TEST: Create payment order & 18% GST calculation
# ===========================================================================
@pytest.mark.asyncio
async def test_create_cashfree_payment_order(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}
    db = info["db"]
    user_id = info["user_a_id"]

    mock_cf_order_response = {
        "cf_order_id": 99887766,
        "order_id": "ORDER_CF_MOCKTEST1",
        "entity": "order",
        "order_currency": "INR",
        "order_amount": 942.82,
        "order_status": "ACTIVE",
        "payment_session_id": "session_mock_abc123",
        "payment_link": "https://payments.cashfree.com/order/#session_mock_abc123"
    }

    mock_client = MockCashfreeClient(post_res=Response(200, json=mock_cf_order_response))
    transport = ASGITransport(app=app)

    with patch("app.services.cashfree_service.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.post(
                "/api/v1/payments/cashfree/order/create",
                json={
                    "plan_id": "PRO_STARTER",
                    "billing_cycle": "monthly",
                    "customer_phone": "9876543210"
                },
                headers=headers
            )

            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["payment_session_id"] == "session_mock_abc123"
            assert data["order_id"].startswith("ORDER_CF_")
            assert data["transaction_id"].startswith("GROWG")
            assert data["status"] == "ACTIVE"
            assert data["amount"] == 942.82
            assert data["base_amount"] == 799.0
            assert data["gst_rate"] == 0.18
            assert data["gst_percentage"] == 18.0
            assert data["gst_amount"] == 143.82

            # Check database persistence
            tx = await db["payment_transactions"].find_one({"order_id": data["order_id"]})
            assert tx is not None
            assert tx["user_id"] == user_id
            assert tx["status"] == "pending"
            assert tx["payment_gateway"] == "Cashfree Payment Gateway"
            assert tx["payment_provider"] == "cashfree"
            assert tx["amount"] == 942.82


# ===========================================================================
# 2. TEST: Successful payment verification & plan activation
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_order_successful_verification(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_SUCCESS_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    # Seed pending transaction
    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_id,
        "user_email": "cashfree_user_a@example.com",
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "base_amount": 799.0,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    })
    await db["payment_subscriptions"].insert_one({
        "order_id": order_id,
        "subscription_id": order_id,
        "user_id": user_id,
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "status": "INITIALIZED",
        "created_at": datetime.now(timezone.utc)
    })

    mock_order_res = {
        "order_id": order_id,
        "cf_order_id": 123456,
        "order_status": "PAID",
        "order_amount": 942.82
    }
    mock_payments_res = [
        {
            "cf_payment_id": 987654,
            "order_id": order_id,
            "payment_status": "SUCCESS",
            "payment_amount": 942.82,
            "payment_group": "upi",
            "bank_reference": "UPI_REF_998877",
            "payment_time": "2026-11-23T10:00:00+05:30"
        }
    ]

    mock_client = MockCashfreeClient(
        get_res_map={
            f"/orders/{order_id}/payments": Response(200, json=mock_payments_res),
            f"/orders/{order_id}": Response(200, json=mock_order_res),
        }
    )
    transport = ASGITransport(app=app)

    with patch("app.services.cashfree_service.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.invoice_service.InvoiceService.send_invoice_email", new_callable=AsyncMock) as mock_invoice_email:

        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.post(
                "/api/v1/payments/cashfree/order/verify",
                json={"order_id": order_id},
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["status"] == "success"
            assert data["verified"] is True
            assert data["payment_mode"] == "Upi"
            assert data["provider_reference"] == "UPI_REF_998877"

            # Verify Plan Activated
            sub = await db["subscriptions"].find_one({"user_id": user_id})
            assert sub is not None
            assert sub["plan_id"] == "PRO_STARTER"
            assert sub["status"] == "active"
            assert sub["verified_payment"] is True

            # Verify Transaction updated to success
            tx = await db["payment_transactions"].find_one({"order_id": order_id})
            assert tx["status"] == "success"
            assert tx["payment_mode"] == "Upi"

            # Verify Invoice email was triggered
            mock_invoice_email.assert_called_once()


# ===========================================================================
# 3. TEST: Failed payment handling
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_order_failed_verification(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_FAILED_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_id,
        "user_email": "cashfree_user_a@example.com",
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    })
    await db["payment_subscriptions"].insert_one({
        "order_id": order_id,
        "subscription_id": order_id,
        "user_id": user_id,
        "plan_id": "PRO_STARTER",
        "status": "INITIALIZED",
        "created_at": datetime.now(timezone.utc)
    })

    mock_order_res = {
        "order_id": order_id,
        "order_status": "EXPIRED",
        "order_amount": 942.82
    }
    mock_payments_res = [
        {
            "cf_payment_id": 987655,
            "payment_status": "FAILED",
            "payment_message": "Bank declined transaction"
        }
    ]

    mock_client = MockCashfreeClient(
        get_res_map={
            f"/orders/{order_id}/payments": Response(200, json=mock_payments_res),
            f"/orders/{order_id}": Response(200, json=mock_order_res),
        }
    )
    transport = ASGITransport(app=app)

    with patch("app.services.cashfree_service.httpx.AsyncClient", return_value=mock_client), \
         patch("app.services.invoice_service.InvoiceService.send_payment_failed_email", new_callable=AsyncMock) as mock_fail_email:

        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.post(
                "/api/v1/payments/cashfree/order/verify",
                json={"order_id": order_id},
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is False
            assert data["status"] == "failed"
            assert data["verified"] is False

            # Verify Plan remained INACTIVE / FREE
            sub = await db["subscriptions"].find_one({"user_id": user_id})
            assert sub is None or sub.get("plan_id") == "FREE"

            # Verify Transaction updated to failed
            tx = await db["payment_transactions"].find_one({"order_id": order_id})
            assert tx["status"] == "failed"
            assert "declined" in str(tx.get("failure_reason")).lower()

            # Verify Failure email triggered
            mock_fail_email.assert_called_once()


# ===========================================================================
# 4. TEST: Pending payment handling (never activates plan)
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_order_pending_verification(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_PENDING_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_id,
        "user_email": "cashfree_user_a@example.com",
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    })
    await db["payment_subscriptions"].insert_one({
        "order_id": order_id,
        "subscription_id": order_id,
        "user_id": user_id,
        "plan_id": "PRO_STARTER",
        "status": "INITIALIZED",
        "created_at": datetime.now(timezone.utc)
    })

    mock_order_res = {
        "order_id": order_id,
        "order_status": "ACTIVE",
        "order_amount": 942.82
    }

    mock_client = MockCashfreeClient(
        get_res_map={
            f"/orders/{order_id}": Response(200, json=mock_order_res),
            f"/orders/{order_id}/payments": Response(200, json=[])
        }
    )
    transport = ASGITransport(app=app)

    with patch("app.services.cashfree_service.httpx.AsyncClient", return_value=mock_client):
        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            res = await ac.get(
                f"/api/v1/payments/cashfree/order/{order_id}",
                headers=headers
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is False
            assert data["status"] == "pending"
            assert data["verified"] is False

            # Verify Plan was NOT activated
            sub = await db["subscriptions"].find_one({"user_id": user_id})
            assert sub is None or sub.get("plan_id") == "FREE"


# ===========================================================================
# 5. TEST: Webhook signature verification (valid and invalid)
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_webhook_signature_verification(setup_test_users):
    info = setup_test_users
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_WH_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "subscription_id": order_id,
        "user_id": user_id,
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    })

    payload = {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id, "order_amount": 942.82},
            "payment": {"payment_status": "SUCCESS", "payment_group": "upi"}
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
        # A. Invalid / Tampered Signature -> MUST return HTTP 400
        bad_headers = {
            "x-webhook-timestamp": "1698765432",
            "x-webhook-signature": "invalid_tampered_signature_base64==",
            "Content-Type": "application/json"
        }
        res_bad = await ac.post("/api/v1/payments/cashfree/webhook", content=raw_body, headers=bad_headers)
        assert res_bad.status_code == 400
        assert "Invalid webhook signature" in res_bad.json()["detail"]

        # B. Valid Signature -> MUST return HTTP 200
        valid_headers = compute_valid_webhook_headers(raw_body)
        with patch("app.services.invoice_service.InvoiceService.send_invoice_email", new_callable=AsyncMock):
            res_good = await ac.post("/api/v1/payments/cashfree/webhook", content=raw_body, headers=valid_headers)
            assert res_good.status_code == 200
            assert res_good.json()["success"] is True


# ===========================================================================
# 6. TEST: Duplicate webhook delivery (idempotency)
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_duplicate_webhook_delivery_idempotency(setup_test_users):
    info = setup_test_users
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_IDEMP_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "subscription_id": order_id,
        "user_id": user_id,
        "plan_id": "PRO_STARTER",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "status": "pending",
        "created_at": datetime.now(timezone.utc)
    })

    payload = {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id, "order_amount": 942.82},
            "payment": {"payment_status": "SUCCESS", "payment_group": "credit_card"}
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    valid_headers = compute_valid_webhook_headers(raw_body)

    transport = ASGITransport(app=app)
    with patch("app.services.invoice_service.InvoiceService.send_invoice_email", new_callable=AsyncMock) as mock_mail:
        async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
            # First delivery
            res1 = await ac.post("/api/v1/payments/cashfree/webhook", content=raw_body, headers=valid_headers)
            assert res1.status_code == 200
            assert mock_mail.call_count == 1

            # Check credit balance
            sub1 = await db["subscriptions"].find_one({"user_id": user_id})
            credits1 = sub1["credits_remaining"]

            # Second duplicate delivery
            res2 = await ac.post("/api/v1/payments/cashfree/webhook", content=raw_body, headers=valid_headers)
            assert res2.status_code == 200
            assert "idempotent" in res2.json()["message"].lower()

            # Verify no double credits
            sub2 = await db["subscriptions"].find_one({"user_id": user_id})
            assert sub2["credits_remaining"] == credits1

            # Verify no duplicate email dispatch
            assert mock_mail.call_count == 1


# ===========================================================================
# 7. TEST: Payment status retrieval endpoint
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_get_order_status_endpoint(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_STATUS_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_id,
        "user_email": "cashfree_user_a@example.com",
        "plan_id": "PRO_STARTER",
        "plan_name": "Pro",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "base_amount": 799.0,
        "status": "success",
        "payment_mode": "Upi",
        "provider_reference": "UPI_998877",
        "created_at": datetime.now(timezone.utc)
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
        res = await ac.get(f"/api/v1/payments/cashfree/order/{order_id}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["order_id"] == order_id
        assert data["status"] == "success"
        assert data["verified"] is True
        assert data["amount"] == 942.82
        assert data["payment_mode"] == "Upi"
        assert data["provider_reference"] == "UPI_998877"


# ===========================================================================
# 8. TEST: Database persistence fields verification
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_database_persistence(setup_test_users):
    info = setup_test_users
    db = info["db"]
    user_id = info["user_a_id"]

    mock_cf_res = {
        "cf_order_id": 883311,
        "order_id": "ORDER_CF_PERSIST_1",
        "order_amount": 942.82,
        "order_status": "ACTIVE",
        "payment_session_id": "session_persist_xyz"
    }

    mock_client = MockCashfreeClient(post_res=Response(200, json=mock_cf_res))

    with patch("app.services.cashfree_service.httpx.AsyncClient", return_value=mock_client):
        res = await CashfreeService.create_order(
            db=db,
            user_id=user_id,
            user_email="cashfree_user_a@example.com",
            plan_id="PRO_STARTER",
            billing_cycle="monthly"
        )
        order_id = res["order_id"]

        tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert tx is not None
        assert tx["order_id"] == order_id
        assert tx["transaction_id"].startswith("GROWG")
        assert tx["user_id"] == user_id
        assert tx["plan_id"] == "PRO_STARTER"
        assert tx["amount"] == 942.82
        assert tx["currency"] == "INR"
        assert tx["status"] == "pending"
        assert tx["created_at"] is not None
        assert tx["updated_at"] is not None


# ===========================================================================
# 9. TEST: Invoice generation and email dispatch trigger
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_invoice_generation_and_email(setup_test_users):
    info = setup_test_users
    db = info["db"]
    user_id = info["user_a_id"]
    order_id = f"ORDER_CF_INV_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_id,
        "user_email": "cashfree_user_a@example.com",
        "user_name": "Cashfree User A",
        "plan_id": "PRO_STARTER",
        "plan_name": "Pro",
        "billing_cycle": "monthly",
        "amount": 942.82,
        "base_amount": 799.0,
        "gst_amount": 143.82,
        "gst_rate": 0.18,
        "gst_percentage": 18.0,
        "currency": "INR",
        "status": "success",
        "payment_mode": "Cards / UPI / NetBanking",
        "created_at": datetime.now(timezone.utc)
    }
    await db["payment_transactions"].insert_one(tx_doc)

    with patch("app.services.msg91_email_service.Msg91EmailService._send_msg91_api", new_callable=AsyncMock) as mock_msg91:
        mock_msg91.return_value = {"status": "success", "data": {"unique_id": "msg91_mock_id"}}
        from app.services.invoice_service import InvoiceService
        mail_res = await InvoiceService.send_invoice_email(db, tx_doc)

        assert mail_res["success"] is True
        updated_tx = await db["payment_transactions"].find_one({"order_id": order_id})
        assert updated_tx["invoice_number"] is not None
        assert updated_tx["invoice_email_sent"] is True


# ===========================================================================
# 10. TEST: Invalid plan / amount rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_invalid_plan_rejection(setup_test_users):
    info = setup_test_users
    headers = {"Authorization": f"Bearer {info['token_a']}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
        # A. Non-existent plan
        res1 = await ac.post(
            "/api/v1/payments/cashfree/order/create",
            json={"plan_id": "INVALID_PLAN_XYZ"},
            headers=headers
        )
        assert res1.status_code == 400
        assert "Invalid plan" in res1.json()["detail"]

        # B. Free plan cannot create payment order
        res2 = await ac.post(
            "/api/v1/payments/cashfree/order/create",
            json={"plan_id": "FREE"},
            headers=headers
        )
        assert res2.status_code == 400
        assert "Cannot create payment for FREE plan" in res2.json()["detail"]


# ===========================================================================
# 11. TEST: Unauthorized access rejection
# ===========================================================================
@pytest.mark.asyncio
async def test_cashfree_unauthorized_access_rejection(setup_test_users):
    info = setup_test_users
    db = info["db"]
    user_a_id = info["user_a_id"]
    token_b = info["token_b"]  # User B trying to access User A's order
    order_id = f"ORDER_CF_AUTH_{uuid.uuid4().hex[:6]}"
    unique_tx_id = f"GROWG{uuid.uuid4().hex[:6].upper()}"

    # Seed User A's transaction
    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": unique_tx_id,
        "user_id": user_a_id,
        "user_email": "cashfree_user_a@example.com",
        "plan_id": "PRO_STARTER",
        "status": "pending",
        "amount": 942.82,
        "created_at": datetime.now(timezone.utc)
    })

    headers_b = {"Authorization": f"Bearer {token_b}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
        # GET order status as User B -> 403 Forbidden
        res_get = await ac.get(f"/api/v1/payments/cashfree/order/{order_id}", headers=headers_b)
        assert res_get.status_code == 403
        assert "Not authorized" in res_get.json()["detail"]

        # POST verify as User B -> 403 Forbidden
        res_verify = await ac.post(
            "/api/v1/payments/cashfree/order/verify",
            json={"order_id": order_id},
            headers=headers_b
        )
        assert res_verify.status_code == 403
        assert "Not authorized" in res_verify.json()["detail"]
