import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
import httpx

from app.main import app
from app.core.database import get_database
from app.core.security import create_access_token
from app.services.invoice_service import InvoiceService
from app.services.payin_service import PayinService
from app.services.cashfree_service import CashfreeService


@pytest.fixture
def mock_msg91_fail_email_success():
    """Mocks MSG91 Email API returning 200 OK for payment failed email."""
    async def _mock_post(self, *args, **kwargs):
        url = kwargs.get("url") or (args[0] if args else "")
        url_str = str(url)
        if "msg91" in url_str:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = {
                "status": "success",
                "data": {"unique_id": "msg91_fail_track_999"},
                "hasError": False,
                "message": "Thank you. Your request has been queued."
            }
            resp.text = '{"status":"success"}'
            return resp
        return await original_async_post(self, *args, **kwargs)
    return _mock_post


original_async_post = httpx.AsyncClient.post


@pytest.mark.asyncio
async def test_01_send_payment_failed_email_direct(mock_msg91_fail_email_success):
    """Verifies that send_payment_failed_email formats MSG91 payload correctly and logs audit."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"ORD_FAIL_TEST_{ts}"
    user_id = f"usr_fail_{ts}"
    unique_email = f"failed_customer_{ts}@example.com"

    # Setup user
    await db["users"].update_one(
        {"_id": user_id},
        {"$set": {"email": unique_email, "name": "Failed Customer", "phone": "+919876543210"}},
        upsert=True
    )

    # Setup failed transaction
    tx_doc = {
        "order_id": order_id,
        "transaction_id": f"TXN_{order_id}",
        "user_id": user_id,
        "user_email": unique_email,
        "user_name": "Failed Customer",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "amount": 942.82,
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "status": "failed",
        "failure_reason": "Bank declined transaction: Insufficient funds",
        "created_at": now,
        "updated_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    with patch("httpx.AsyncClient.post", new=mock_msg91_fail_email_success):
        res = await InvoiceService.send_payment_failed_email(db, tx_doc)
        assert res["success"] is True
        assert res["status"] == "SENT"
        assert res["unique_id"] == "msg91_fail_track_999"

    # Verify audit in DB
    updated = await db["payment_transactions"].find_one({"order_id": order_id})
    assert updated["payment_failed_email_sent"] is True
    assert updated["payment_failed_email_status"] == "SENT"


@pytest.mark.asyncio
async def test_02_idempotency_prevents_duplicate_failure_emails():
    """Verifies that duplicate failure emails are skipped unless retry=True."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"ORD_IDEMP_FAIL_{ts}"
    user_id = f"usr_idemp_{ts}"

    tx_doc = {
        "order_id": order_id,
        "user_id": user_id,
        "user_email": "customer@example.com",
        "status": "failed",
        "payment_failed_email_sent": True,
        "payment_failed_email_status": "SENT"
    }
    await db["payment_transactions"].insert_one(tx_doc)

    with patch("httpx.AsyncClient.post") as mock_post:
        res = await InvoiceService.send_payment_failed_email(db, tx_doc, retry=False)
        assert res["success"] is True
        assert res.get("already_sent") is True
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_03_no_failed_email_for_successful_payments():
    """Verifies that send_payment_failed_email refuses to send if payment status is 'success'."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"ORD_SUCC_{ts}"
    user_id = f"usr_succ_{ts}"

    tx_doc = {
        "order_id": order_id,
        "user_id": user_id,
        "user_email": "customer@example.com",
        "status": "success"
    }
    await db["payment_transactions"].insert_one(tx_doc)

    with patch("httpx.AsyncClient.post") as mock_post:
        res = await InvoiceService.send_payment_failed_email(db, tx_doc)
        assert res["success"] is False
        assert res.get("skipped") is True
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_04_cashfree_webhook_failed_mandate_triggers_email():
    """Verifies that Cashfree webhook with SUBSCRIPTION_FAILED updates DB and triggers failed email."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    sub_id = f"SUB_FAIL_{ts}"
    user_id = f"usr_cf_fail_{ts}"

    await db["payment_subscriptions"].insert_one({
        "subscription_id": sub_id,
        "user_id": user_id,
        "plan_id": "STARTER",
        "status": "INITIALIZED",
        "recurring_amount": 942.82,
        "created_at": now
    })
    await db["payment_transactions"].insert_one({
        "order_id": sub_id,
        "user_id": user_id,
        "user_email": "user_cf_fail@example.com",
        "user_name": "CF User",
        "plan_id": "STARTER",
        "amount": 942.82,
        "status": "pending",
        "created_at": now
    })

    webhook_payload = {
        "type": "SUBSCRIPTION_FAILED",
        "data": {
            "subscription": {
                "subscription_id": sub_id,
                "subscription_status": "FAILED"
            }
        },
        "message": "Mandate authorization rejected by bank"
    }

    mock_send = MagicMock()
    async def _async_mock_send(*args, **kwargs):
        mock_send(*args, **kwargs)
        return {"success": True, "status": "SENT"}

    with patch("app.services.invoice_service.InvoiceService.send_payment_failed_email", side_effect=_async_mock_send):
        res = await CashfreeService.process_webhook(db, webhook_payload)
        assert res["success"] is True
        assert mock_send.call_count == 1
        assert "rejected by bank" in mock_send.call_args[1]["failure_reason"]

    # Verify transaction status was updated to failed
    tx = await db["payment_transactions"].find_one({"order_id": sub_id})
    assert tx["status"] == "failed"


@pytest.mark.asyncio
async def test_05_payin_callback_failure_triggers_email():
    """Verifies that Payin callback with failure response code triggers send_payment_failed_email."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"PAYIN_FAIL_{ts}"
    user_id = f"usr_payin_fail_{ts}"

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "user_email": "payin_fail@example.com",
        "user_name": "Payin User",
        "plan_id": "STARTER",
        "amount": 942.82,
        "status": "pending",
        "created_at": now
    })

    callback_payload = {
        "orderId": order_id,
        "responseCode": "102",
        "status": "FAILED",
        "message": "User aborted payment process on bank portal"
    }

    mock_send = MagicMock()
    async def _async_mock_send(*args, **kwargs):
        mock_send(*args, **kwargs)
        return {"success": True, "status": "SENT"}

    with patch("app.services.invoice_service.InvoiceService.send_payment_failed_email", side_effect=_async_mock_send):
        res = await PayinService.process_callback(db, callback_payload, {})
        assert res["success"] is False
        assert res["status"] == "failed"
        assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_06_resend_failed_email_endpoint():
    """Verifies POST /api/v1/payments/transactions/{id}/resend-failed-email."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"ORD_RESEND_{ts}"
    user_id = "6ae07df09bac56baccb9f2c5"
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": f"TXN_{order_id}",
        "user_id": user_id,
        "user_email": "resend_user@example.com",
        "user_name": "Resend User",
        "plan_id": "STARTER",
        "amount": 942.82,
        "status": "failed",
        "failure_reason": "Timeout waiting for OTP",
        "created_at": now
    })

    mock_send = MagicMock()
    async def _async_mock_send(*args, **kwargs):
        mock_send(*args, **kwargs)
        return {"success": True, "status": "SENT", "message": "Dispatched"}

    with patch("app.services.invoice_service.InvoiceService.send_payment_failed_email", side_effect=_async_mock_send):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/payments/transactions/{order_id}/resend-failed-email",
                headers=headers
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True
            assert mock_send.call_count == 1


@pytest.mark.asyncio
async def test_07_failed_email_status_endpoint():
    """Verifies GET /api/v1/payments/transactions/{id}/failed-email-status."""
    db = get_database()
    now = datetime.now(timezone.utc)
    ts = now.strftime('%H%M%S%f')
    order_id = f"ORD_STAT_{ts}"
    user_id = "6ae07df09bac56baccb9f2c5"
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    await db["payment_transactions"].insert_one({
        "order_id": order_id,
        "transaction_id": f"TXN_{order_id}",
        "user_id": user_id,
        "status": "failed",
        "failure_reason": "Card limit exceeded",
        "payment_failed_email_sent": True,
        "payment_failed_email_status": "SENT",
        "payment_failed_email_recipient": "status_user@example.com",
        "created_at": now
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/payments/transactions/{order_id}/failed-email-status",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["failed_email_delivery"]["sent"] is True
        assert data["failed_email_delivery"]["status"] == "SENT"
        assert data["failure_reason"] == "Card limit exceeded"
