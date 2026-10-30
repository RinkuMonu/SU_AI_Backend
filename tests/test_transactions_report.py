import re
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.services.subscription_service import SubscriptionService
from app.services.payin_service import PayinService
from app.services.pdf_service import PDFService

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    settings.PAYIN_URL = "http://mock.finuniques.in/payin"
    settings.PAYIN_TOKEN = "mock_token"
    yield
    close_mongo_connection()

async def create_test_user(db, name: str = "Test User"):
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
    await SubscriptionService.get_or_create_subscription(db, str(user_id))
    token = create_access_token(subject=str(user_id))
    return str(user_id), token, user_doc

original_post = AsyncClient.post

async def mock_finunique_post(self, url, *args, **kwargs):
    if "finuniques.in" in str(url) or "mock.finuniques.in" in str(url):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "success": True,
            "data": {
                "redirectURL": "upi://pay?pa=dhandagrow@icici&pn=DhandaGrow&am=1.00&cu=INR",
                "redirectEx": "https://gateway.finuniques.in/checkout/mock123",
                "reference": "FIN_MOCK_REF_9999",
                "qrCode": "upi://pay?pa=dhandagrow@icici&pn=DhandaGrow&am=1.00&cu=INR"
            }
        }
        return mock_res
    return await original_post(self, url, *args, **kwargs)


# 1. Dynamic Unique Transaction ID & Concurrency Test
async def test_dynamic_transaction_id_generation_and_concurrency():
    db = get_database()
    
    # Sequential generation check
    id1 = await PayinService.generate_transaction_id(db)
    id2 = await PayinService.generate_transaction_id(db)
    
    assert id1.startswith("GROWG")
    assert id2.startswith("GROWG")
    num1 = int(id1.replace("GROWG", ""))
    num2 = int(id2.replace("GROWG", ""))
    assert num2 == num1 + 1

    # Concurrent generation test: 10 concurrent requests must never generate duplicate IDs
    tasks = [PayinService.generate_transaction_id(db) for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 10
    assert len(set(results)) == 10, "Duplicate transaction IDs detected during concurrent generation!"
    for tid in results:
        assert re.match(r"^GROWG\d{3,}$", tid)


# 2. Payment Creation & Initial Transaction Record
async def test_create_payment_order_with_growg_transaction_id():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Rajesh Kumar")
    
    with patch.object(AsyncClient, "post", mock_finunique_post):
        res = await PayinService.create_payment(
            db=db,
            user_id=uid,
            user_email=udoc["email"],
            plan_id="TEST_PLAN",
            billing_cycle="monthly",
            user_name="Rajesh Kumar",
            user_mobile=udoc["phone_number"]
        )
        
        assert res["success"] is True
        assert "transaction_id" in res
        txn_id = res["transaction_id"]
        assert txn_id.startswith("GROWG")
        order_id = res["order_id"]
        assert order_id.startswith("ORDER_")
        
        # Verify MongoDB storage in payment_transactions collection
        doc = await db["payment_transactions"].find_one({"order_id": order_id})
        assert doc is not None
        assert doc["transaction_id"] == txn_id
        assert doc["user_id"] == uid
        assert doc["user_name"] == "Rajesh Kumar"
        assert doc["user_email"] == udoc["email"]
        assert doc["user_phone"] == udoc["phone_number"]
        assert doc["plan_id"] == "TEST_PLAN"
        assert doc["status"] in ["pending", "initiated"]
        assert doc["currency"] == "INR"
        assert doc["amount"] == 1.0
        assert doc["payment_mode"] in ["QR Code", "Unknown"]
        assert doc["payment_gateway"] == "Finunique Payin"
        assert doc["payment_provider"] == "Finunique"


# 3. Status Verification & Payment Mode Extraction
async def test_payment_status_verification_and_mode_extraction():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Pooja Sharma")
    
    with patch.object(AsyncClient, "post", mock_finunique_post):
        pay_res = await PayinService.create_payment(
            db=db,
            user_id=uid,
            user_email=udoc["email"],
            plan_id="TEST_PLAN",
            billing_cycle="monthly",
            user_name="Pooja Sharma",
            user_mobile=udoc["phone_number"]
        )
        order_id = pay_res["order_id"]
        original_txn_id = pay_res["transaction_id"]

    # Gateway callback payload with UPI payment mode and gateway transaction ID
    callback_payload = {
        "orderId": order_id,
        "status": "SUCCESS",
        "responseCode": "100",
        "amount": 1.0,
        "paymentMode": "UPI",
        "pgTransId": "GATEWAY_TXN_UPI_998877",
        "userId": uid,
        "plan_id": "TEST_PLAN"
    }

    cb_res = await PayinService.process_callback(db, callback_payload, from_provider_verification=True)
    assert cb_res["success"] is True
    assert cb_res["status"] == "success"

    # Verify updated record in MongoDB
    updated = await db["payment_transactions"].find_one({"order_id": order_id})
    assert updated["status"] == "success"
    # Preserves original GROWG transaction ID throughout
    assert updated["transaction_id"] == original_txn_id
    assert updated["payment_mode"] == "UPI"
    assert updated["gateway_transaction_id"] == "GATEWAY_TXN_UPI_998877"
    assert updated["completed_at"] is not None

    # Verify idempotency: second callback does not re-grant credits
    sub_before = await db["subscriptions"].find_one({"user_id": uid})
    credits_before = sub_before.get("credits_remaining")

    second_cb = await PayinService.process_callback(db, callback_payload, from_provider_verification=True)
    assert second_cb["status"] == "success"
    assert second_cb.get("message") == "Already processed"

    sub_after = await db["subscriptions"].find_one({"user_id": uid})
    assert sub_after.get("credits_remaining") == credits_before


# 4. User Transaction Report API with Pagination, Filters & Search
async def test_user_transactions_report_api():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Vikram Singh")
    uid_other, token_other, _ = await create_test_user(db, name="Other User")
    
    now = datetime.now(timezone.utc)
    
    # Insert 3 transactions for Vikram
    tx1 = {
        "transaction_id": await PayinService.generate_transaction_id(db),
        "order_id": "ORDER_TX1_VIKRAM",
        "user_id": uid,
        "user_name": "Vikram Singh",
        "user_email": udoc["email"],
        "plan_id": "PRO",
        "plan_name": "Pro Plan",
        "billing_cycle": "monthly",
        "amount": 3538.82,
        "base_amount": 2999.0,
        "gst_amount": 539.82,
        "currency": "INR",
        "payment_mode": "UPI",
        "payment_gateway": "Finunique Payin",
        "gateway_transaction_id": "UPI_REF_111",
        "status": "success",
        "purchased_credits": 100,
        "credits_included": 100,
        "created_at": now - timedelta(days=2),
        "completed_at": now - timedelta(days=2),
    }
    tx2 = {
        "transaction_id": await PayinService.generate_transaction_id(db),
        "order_id": "ORDER_TX2_VIKRAM",
        "user_id": uid,
        "user_name": "Vikram Singh",
        "user_email": udoc["email"],
        "plan_id": "BASIC",
        "plan_name": "Basic Starter Plan",
        "billing_cycle": "monthly",
        "amount": 1178.82,
        "currency": "INR",
        "payment_mode": "Net Banking",
        "payment_gateway": "Finunique Payin",
        "gateway_transaction_id": "NB_REF_222",
        "status": "failed",
        "failure_reason": "Insufficient balance",
        "created_at": now - timedelta(days=1),
        "completed_at": now - timedelta(days=1),
    }
    tx3 = {
        "transaction_id": await PayinService.generate_transaction_id(db),
        "order_id": "ORDER_TX3_VIKRAM",
        "user_id": uid,
        "user_name": "Vikram Singh",
        "user_email": udoc["email"],
        "plan_id": "TEST_PLAN",
        "plan_name": "₹1 Test Plan",
        "billing_cycle": "monthly",
        "amount": 1.0,
        "currency": "INR",
        "payment_mode": "QR Code",
        "payment_gateway": "Finunique Payin",
        "status": "pending",
        "created_at": now,
    }
    # Insert 1 transaction for Other User
    tx_other = {
        "transaction_id": await PayinService.generate_transaction_id(db),
        "order_id": "ORDER_OTHER_USER",
        "user_id": uid_other,
        "user_name": "Other User",
        "plan_id": "ENTERPRISE",
        "plan_name": "Enterprise Plan",
        "amount": 9999.0,
        "currency": "INR",
        "status": "success",
        "created_at": now,
    }

    await db["payment_transactions"].insert_many([tx1, tx2, tx3, tx_other])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # 4a. Basic listing: verify Vikram sees only his 3 transactions, sorted newest first
        res = await ac.get("/api/v1/transactions", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["total"] == 3
        items = data["data"]
        assert len(items) == 3
        assert items[0]["order_id"] == "ORDER_TX3_VIKRAM"
        assert items[1]["order_id"] == "ORDER_TX2_VIKRAM"
        assert items[2]["order_id"] == "ORDER_TX1_VIKRAM"
        for item in items:
            assert item["transaction_id"].startswith("GROWG")
            assert item["user_id"] == uid

        # 4b. Pagination test (page=1, limit=2)
        res_page = await ac.get("/api/v1/transactions?page=1&limit=2", headers=headers)
        assert res_page.status_code == 200
        p_data = res_page.json()
        assert len(p_data["data"]) == 2
        assert p_data["total"] == 3
        assert p_data["total_pages"] == 2

        # 4c. Status filter (status=SUCCESS)
        res_succ = await ac.get("/api/v1/transactions?status=SUCCESS", headers=headers)
        assert res_succ.status_code == 200
        s_data = res_succ.json()
        assert s_data["total"] == 1
        assert s_data["data"][0]["order_id"] == "ORDER_TX1_VIKRAM"

        # 4d. Payment mode filter (payment_mode=Net Banking)
        res_mode = await ac.get("/api/v1/transactions?payment_mode=Net Banking", headers=headers)
        assert res_mode.status_code == 200
        m_data = res_mode.json()
        assert m_data["total"] == 1
        assert m_data["data"][0]["order_id"] == "ORDER_TX2_VIKRAM"

        # 4e. Search filter by GROWG transaction ID
        target_tid = tx1["transaction_id"]
        res_search = await ac.get(f"/api/v1/transactions?search={target_tid}", headers=headers)
        assert res_search.status_code == 200
        sr_data = res_search.json()
        assert sr_data["total"] == 1
        assert sr_data["data"][0]["transaction_id"] == target_tid

        # 4f. User isolation: other user cannot see Vikram's transactions
        headers_other = {"Authorization": f"Bearer {token_other}"}
        res_other = await ac.get("/api/v1/transactions", headers=headers_other)
        assert res_other.status_code == 200
        o_data = res_other.json()
        assert o_data["total"] == 1
        assert o_data["data"][0]["order_id"] == "ORDER_OTHER_USER"


# 5. Single Transaction Details API with Ownership Verification
async def test_single_transaction_details_and_access_control():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Sunita Rao")
    uid_other, token_other, _ = await create_test_user(db, name="Intruder")

    tid = await PayinService.generate_transaction_id(db)
    tx = {
        "transaction_id": tid,
        "order_id": "ORDER_SUNITA_PRIVATE",
        "user_id": uid,
        "user_name": "Sunita Rao",
        "user_email": udoc["email"],
        "plan_id": "PRO",
        "plan_name": "Pro Plan",
        "amount": 3538.82,
        "currency": "INR",
        "payment_mode": "UPI",
        "status": "success",
        "created_at": datetime.now(timezone.utc),
    }
    await db["payment_transactions"].insert_one(tx)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_owner = {"Authorization": f"Bearer {token}"}
        headers_intruder = {"Authorization": f"Bearer {token_other}"}

        # 5a. Owner retrieves transaction by GROWG ID
        res = await ac.get(f"/api/v1/transactions/{tid}", headers=headers_owner)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["transaction_id"] == tid
        assert data["data"]["order_id"] == "ORDER_SUNITA_PRIVATE"

        # 5b. Owner retrieves transaction by order_id
        res_ord = await ac.get(f"/api/v1/transactions/ORDER_SUNITA_PRIVATE", headers=headers_owner)
        assert res_ord.status_code == 200
        assert res_ord.json()["data"]["transaction_id"] == tid

        # 5c. Intruder attempts to retrieve Sunita's transaction -> 403 Forbidden
        res_forbidden = await ac.get(f"/api/v1/transactions/{tid}", headers=headers_intruder)
        assert res_forbidden.status_code == 403
        assert "Forbidden" in res_forbidden.json()["detail"]

        # 5d. Non-existent transaction -> 404 Not Found
        res_404 = await ac.get(f"/api/v1/transactions/GROWG999999", headers=headers_owner)
        assert res_404.status_code == 404


# 6. Transaction Report Export API (CSV and PDF)
async def test_transaction_export_csv_and_pdf():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Anil Kapoor")

    tid = await PayinService.generate_transaction_id(db)
    tx = {
        "transaction_id": tid,
        "order_id": "ORDER_ANIL_EXPORT",
        "user_id": uid,
        "user_name": "Anil Kapoor",
        "user_email": udoc["email"],
        "plan_id": "PRO",
        "plan_name": "Pro Plan",
        "billing_cycle": "monthly",
        "amount": 3538.82,
        "base_amount": 2999.0,
        "gst_amount": 539.82,
        "currency": "INR",
        "payment_mode": "UPI",
        "payment_gateway": "Finunique Payin",
        "gateway_transaction_id": "EXPORT_GW_REF",
        "status": "success",
        "credits_included": 100,
        "created_at": datetime.now(timezone.utc),
    }
    await db["payment_transactions"].insert_one(tx)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # 6a. CSV Export
        res_csv = await ac.get("/api/v1/transactions/export?format=csv", headers=headers)
        assert res_csv.status_code == 200
        assert "text/csv" in res_csv.headers["content-type"]
        assert "attachment" in res_csv.headers["content-disposition"]
        csv_text = res_csv.content.decode("utf-8-sig")
        assert "Transaction ID" in csv_text
        assert tid in csv_text
        assert "ORDER_ANIL_EXPORT" in csv_text
        assert "3538.82" in csv_text
        assert "SUCCESS" in csv_text

        # 6b. PDF Export
        res_pdf = await ac.get("/api/v1/transactions/export?format=pdf", headers=headers)
        assert res_pdf.status_code == 200
        assert "application/pdf" in res_pdf.headers["content-type"]
        assert "attachment" in res_pdf.headers["content-disposition"]
        assert res_pdf.content.startswith(b"%PDF-")
        assert len(res_pdf.content) > 1000


# 7. Downloadable Receipt API
async def test_download_transaction_receipt_pdf():
    db = get_database()
    uid, token, udoc = await create_test_user(db, name="Deepak Joshi")
    uid_other, token_other, _ = await create_test_user(db, name="Hacker")

    tid = await PayinService.generate_transaction_id(db)
    tx = {
        "transaction_id": tid,
        "order_id": "ORDER_DEEPAK_RECEIPT",
        "user_id": uid,
        "user_name": "Deepak Joshi",
        "user_email": udoc["email"],
        "user_phone": udoc["phone_number"],
        "plan_id": "PRO",
        "plan_name": "Pro Business Plan",
        "billing_cycle": "monthly",
        "amount": 3538.82,
        "base_amount": 2999.0,
        "gst_amount": 539.82,
        "gst_rate": 0.18,
        "currency": "INR",
        "payment_mode": "QR Code",
        "payment_gateway": "Finunique Payin",
        "gateway_transaction_id": "RECEIPT_GW_12345",
        "status": "success",
        "credits_included": 100,
        "created_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }
    await db["payment_transactions"].insert_one(tx)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_owner = {"Authorization": f"Bearer {token}"}
        headers_hacker = {"Authorization": f"Bearer {token_other}"}

        # 7a. Owner downloads receipt
        res = await ac.get(f"/api/v1/transactions/{tid}/receipt", headers=headers_owner)
        assert res.status_code == 200
        assert "application/pdf" in res.headers["content-type"]
        assert f"receipt_{tid}.pdf" in res.headers["content-disposition"]
        assert res.content.startswith(b"%PDF-")
        assert len(res.content) > 1000

        # 7b. Non-owner cannot download Deepak's receipt -> 403 Forbidden
        res_denied = await ac.get(f"/api/v1/transactions/{tid}/receipt", headers=headers_hacker)
        assert res_denied.status_code == 403
        assert "Forbidden" in res_denied.json()["detail"]

