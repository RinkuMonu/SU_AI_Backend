import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import httpx
from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database
from app.core.security import create_access_token
from app.services.invoice_service import InvoiceService
from app.services.payin_service import PayinService
from app.services.cashfree_service import CashfreeService
from app.services.pdf_service import PDFService
from app.core.config import settings


original_async_post = httpx.AsyncClient.post


@pytest.fixture
def mock_msg91_success():
    """Mocks MSG91 Email API returning 200 OK with success JSON."""
    async def _mock_post(self, *args, **kwargs):
        url = kwargs.get("url") or (args[0] if args else "")
        url_str = str(url)
        if "msg91" in url_str:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = {
                "status": "success",
                "data": {"unique_id": "msg91_test_uid_12345"},
                "hasError": False,
                "message": "Thank you. Your request has been queued."
            }
            resp.text = '{"status":"success"}'
            return resp
        return await original_async_post(self, *args, **kwargs)
    return _mock_post


@pytest.fixture
def mock_msg91_failure():
    """Mocks MSG91 Email API returning 500 / network error."""
    async def _mock_post(self, *args, **kwargs):
        url = kwargs.get("url") or (args[0] if args else "")
        url_str = str(url)
        if "msg91" in url_str:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 500
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = {
                "status": "error",
                "hasError": True,
                "message": "Internal gateway failure"
            }
            resp.text = '{"status":"error"}'
            return resp
        return await original_async_post(self, *args, **kwargs)
    return _mock_post


@pytest.mark.asyncio
async def test_01_invoice_metadata_and_18_percent_gst_generation():
    """Verifies that invoice record generation calculates 18% GST and unique invoice number."""
    db = get_database()
    now = datetime.now(timezone.utc)
    order_id = f"ORD_INV_TEST_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-TEST-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_name": "Rohan Gupta",
        "user_email": "rohan@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "created_at": now,
        "completed_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    enriched_tx = await InvoiceService.ensure_invoice_record(db, tx_doc)
    assert enriched_tx["invoice_number"].startswith("INV-")
    assert enriched_tx["base_amount"] == 799.00
    assert enriched_tx["gst_amount"] == 143.82
    assert enriched_tx["total_payable"] == 942.82
    assert enriched_tx["invoice_download_token"] is not None
    assert "token=" in enriched_tx["invoice_download_url"]

    # Verify audit invoice record in DB
    db_tx = await db["payment_transactions"].find_one({"order_id": order_id})
    assert db_tx["invoice_number"] == enriched_tx["invoice_number"]
    assert db_tx["invoice_download_token"] == enriched_tx["invoice_download_token"]


@pytest.mark.asyncio
async def test_02_successful_payment_auto_sends_msg91_invoice_email(mock_msg91_success):
    """Verifies automatic MSG91 invoice email dispatch with correct dynamic variables on payment success."""
    db = get_database()
    now = datetime.now(timezone.utc)
    order_id = f"ORD_AUTO_SEND_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-INV-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_name": "Priya Sharma",
        "user_email": "priya@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "created_at": now,
        "completed_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    captured_payloads = []

    async def _inspect_post(self, *args, **kwargs):
        url = kwargs.get("url") or (args[0] if args else "")
        if "msg91" in str(url):
            captured_payloads.append({"url": str(url), "json": kwargs.get("json"), "headers": kwargs.get("headers")})
        return await mock_msg91_success(self, *args, **kwargs)

    with patch("httpx.AsyncClient.post", side_effect=_inspect_post, autospec=True):
        result = await InvoiceService.send_invoice_email(db, tx_doc)

    assert result["success"] is True
    assert result["status"] == "SENT"
    assert len(captured_payloads) == 1

    payload = captured_payloads[0]["json"]
    headers = captured_payloads[0]["headers"]

    # Verify MSG91 API configuration contract
    assert captured_payloads[0]["url"] == "https://control.msg91.com/api/v5/email/send"
    assert headers["authkey"] is not None
    assert headers["Content-Type"] == "application/json"
    assert payload["template_id"] == "auto_pay_templete"
    assert payload["from"]["email"] == "no-reply@dhandagrow.com"
    assert payload["domain"] == "dhandagrow.com"

    # Verify dynamic variables
    recipient = payload["recipients"][0]
    assert recipient["to"][0]["email"] == "priya@dhandagrow.com"
    vars_dict = recipient["variables"]
    assert vars_dict["customer_name"] == "Priya Sharma"
    assert vars_dict["plan_name"] == "Starter Plan"
    assert vars_dict["base_amount"] == "799.00"
    assert vars_dict["gst_amount"] == "143.82"
    assert vars_dict["total_amount"] == "942.82"
    assert vars_dict["payment_id"] == tx_id
    assert "token=" in vars_dict["invoice_link"]

    # Verify transaction record state in database
    updated_tx = await db["payment_transactions"].find_one({"order_id": order_id})
    assert updated_tx["invoice_email_sent"] is True
    assert updated_tx["invoice_email_status"] == "SENT"
    assert updated_tx["invoice_email_recipient"] == "priya@dhandagrow.com"
    assert updated_tx["invoice_email_attempts"] == 1


@pytest.mark.asyncio
async def test_03_no_invoice_email_for_pending_failed_or_unverified_payments():
    """Strictly prevents invoice email dispatch for pending, failed, or cancelled transactions."""
    db = get_database()
    now = datetime.now(timezone.utc)

    # 1. Pending payment
    pending_tx = {
        "order_id": f"ORD_PENDING_{now.strftime('%H%M%S%f')}",
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_email": "user@dhandagrow.com",
        "status": "pending",
        "amount": 942.82
    }
    await db["payment_transactions"].insert_one(pending_tx)
    res_pending = await InvoiceService.send_invoice_email(db, pending_tx)
    assert res_pending["success"] is False
    assert res_pending["skipped"] is True
    assert res_pending["status"] == "SKIPPED_UNVERIFIED"

    # 2. Failed payment
    failed_tx = {
        "order_id": f"ORD_FAILED_{now.strftime('%H%M%S%f')}",
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_email": "user@dhandagrow.com",
        "status": "failed",
        "amount": 942.82
    }
    await db["payment_transactions"].insert_one(failed_tx)
    res_failed = await InvoiceService.send_invoice_email(db, failed_tx)
    assert res_failed["success"] is False
    assert res_failed["skipped"] is True
    assert res_failed["status"] == "SKIPPED_UNVERIFIED"

    # 3. Cancelled payment
    cancelled_tx = {
        "order_id": f"ORD_CANCELLED_{now.strftime('%H%M%S%f')}",
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_email": "user@dhandagrow.com",
        "status": "cancelled",
        "amount": 942.82
    }
    await db["payment_transactions"].insert_one(cancelled_tx)
    res_cancelled = await InvoiceService.send_invoice_email(db, cancelled_tx)
    assert res_cancelled["success"] is False
    assert res_cancelled["skipped"] is True


@pytest.mark.asyncio
async def test_04_duplicate_payment_webhook_idempotency(mock_msg91_success):
    """Verifies that duplicate callbacks/webhooks do NOT trigger duplicate invoice emails or duplicate invoices."""
    db = get_database()
    now = datetime.now(timezone.utc)
    order_id = f"ORD_IDEM_TEST_{now.strftime('%H%M%S%f')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": f"GROWG-DUP-{now.strftime('%H%M%S')}",
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_name": "Duplicate Tester",
        "user_email": "dup@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "invoice_email_sent": True,  # Already sent in initial pass
        "invoice_email_status": "SENT",
        "invoice_number": "INV-202610-DUP001",
        "invoice_email_attempts": 1,
        "created_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    call_count = 0

    async def _mock_post_count(self, *args, **kwargs):
        nonlocal call_count
        url = kwargs.get("url") or (args[0] if args else "")
        if "msg91" in str(url):
            call_count += 1
        return await mock_msg91_success(self, *args, **kwargs)

    with patch("httpx.AsyncClient.post", side_effect=_mock_post_count, autospec=True):
        # Trigger second webhook / confirmation
        result = await InvoiceService.send_invoice_email(db, tx_doc, retry=False)

    assert result["success"] is True
    assert result.get("already_sent") is True
    # Zero additional HTTP calls made to MSG91
    assert call_count == 0
    # Invoice number preserved
    assert result["invoice_number"] == "INV-202610-DUP001"


@pytest.mark.asyncio
async def test_05_failed_email_delivery_and_safe_retry(mock_msg91_failure, mock_msg91_success):
    """Verifies that MSG91 failure is safely recorded and retry works without duplicating invoice number."""
    db = get_database()
    now = datetime.now(timezone.utc)
    order_id = f"ORD_RETRY_TEST_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-FAIL-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_name": "Failure Tester",
        "user_email": "fail@dhandagrow.com",
        "plan_id": "PRO",
        "plan_name": "Pro Plan",
        "base_amount": 1999.00,
        "gst_amount": 359.82,
        "total_payable": 2358.82,
        "amount": 2358.82,
        "currency": "INR",
        "status": "success",
        "created_at": now,
        "completed_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    # 1. First attempt fails due to MSG91 API error
    with patch("httpx.AsyncClient.post", side_effect=mock_msg91_failure, autospec=True):
        fail_res = await InvoiceService.send_invoice_email(db, tx_doc)

    assert fail_res["success"] is False
    assert fail_res["status"] == "FAILED"
    original_invoice_number = fail_res["invoice_number"]

    # Transaction audit state updated
    db_tx_after_fail = await db["payment_transactions"].find_one({"order_id": order_id})
    assert db_tx_after_fail["invoice_email_sent"] is False
    assert db_tx_after_fail["invoice_email_status"] == "FAILED"
    assert db_tx_after_fail["invoice_email_attempts"] == 1
    assert db_tx_after_fail["invoice_number"] == original_invoice_number

    # 2. Retry attempt succeeds
    with patch("httpx.AsyncClient.post", side_effect=mock_msg91_success, autospec=True):
        retry_res = await InvoiceService.retry_invoice_email(
            db,
            transaction_id_or_order_id=order_id,
            authenticated_user_id="6ae07df09bac56baccb9f2c5"
        )

    assert retry_res["success"] is True
    assert retry_res["status"] == "SENT"
    # Exact same invoice number preserved (no duplicate invoice created)
    assert retry_res["invoice_number"] == original_invoice_number

    db_tx_after_retry = await db["payment_transactions"].find_one({"order_id": order_id})
    assert db_tx_after_retry["invoice_email_sent"] is True
    assert db_tx_after_retry["invoice_email_status"] == "SENT"
    assert db_tx_after_retry["invoice_email_attempts"] == 2


@pytest.mark.asyncio
async def test_06_secure_receipt_download_with_token_and_unauthorized_rejection():
    """Verifies that token-based receipt download works without session login, while unauthorized requests fail."""
    db = get_database()
    now = datetime.now(timezone.utc)
    order_id = f"ORD_DOWNLOAD_TEST_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-DL-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": "6ae07df09bac56baccb9f2c5",
        "user_name": "Download Tester",
        "user_email": "dl@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "created_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)
    enriched = await InvoiceService.ensure_invoice_record(db, tx_doc)
    valid_token = enriched["invoice_download_token"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Unauthenticated request without token -> 401 Unauthorized
        res_no_auth = await ac.get(f"/api/v1/payments/transactions/{tx_id}/receipt")
        assert res_no_auth.status_code == 401

        # 2. Unauthenticated request with invalid token -> 401 Unauthorized
        res_bad_tok = await ac.get(f"/api/v1/payments/transactions/{tx_id}/receipt?token=invalid_token_123")
        assert res_bad_tok.status_code == 401

        # 3. Unauthenticated request with valid secure token -> 200 OK + PDF binary
        res_valid_tok = await ac.get(f"/api/v1/payments/transactions/{tx_id}/receipt?token={valid_token}")
        assert res_valid_tok.status_code == 200
        assert res_valid_tok.headers["content-type"] == "application/pdf"
        assert res_valid_tok.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_07_resend_invoice_email_api_endpoint(mock_msg91_success):
    """Verifies that the resend-invoice-email API endpoint works for authenticated transaction owner."""
    db = get_database()
    now = datetime.now(timezone.utc)
    user_id = "6ae07df09bac56baccb9f2c5"
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"_id": ObjectId(user_id), "email": "api_test@dhandagrow.com", "role": "businessman"}},
        upsert=True
    )
    order_id = f"ORD_RESEND_API_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-RESEND-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": user_id,
        "user_name": "API Tester",
        "user_email": "api_test@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "created_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    with patch("httpx.AsyncClient.post", side_effect=mock_msg91_success, autospec=True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(f"/api/v1/payments/transactions/{tx_id}/resend-invoice-email", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["status"] == "SENT"


@pytest.mark.asyncio
async def test_08_invoice_status_api_endpoint():
    """Verifies that invoice-status API returns delivery status, audit timestamps, and invoice number."""
    db = get_database()
    now = datetime.now(timezone.utc)
    user_id = "6ae07df09bac56baccb9f2c5"
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"_id": ObjectId(user_id), "email": "status_test@dhandagrow.com", "role": "businessman"}},
        upsert=True
    )
    order_id = f"ORD_STATUS_API_{now.strftime('%H%M%S%f')}"
    tx_id = f"GROWG-STATUS-{now.strftime('%H%M%S')}"

    tx_doc = {
        "order_id": order_id,
        "transaction_id": tx_id,
        "user_id": user_id,
        "user_name": "Status Tester",
        "user_email": "status_test@dhandagrow.com",
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "base_amount": 799.00,
        "gst_amount": 143.82,
        "total_payable": 942.82,
        "amount": 942.82,
        "currency": "INR",
        "status": "success",
        "invoice_number": "INV-202610-STAT01",
        "invoice_email_sent": True,
        "invoice_email_status": "SENT",
        "invoice_email_attempts": 1,
        "invoice_email_sent_at": now,
        "created_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/payments/transactions/{tx_id}/invoice-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["invoice_number"] == "INV-202610-STAT01"
        assert data["email_delivery"]["sent"] is True
        assert data["email_delivery"]["status"] == "SENT"
        assert data["email_delivery"]["attempts"] == 1
