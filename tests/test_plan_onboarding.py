import io
import uuid
import random
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.core.config import settings
from app.core.billing_config import PLANS, BILLING_CYCLES

pytestmark = pytest.mark.asyncio

_phone_counter = 500


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield


@pytest.fixture(autouse=True)
def mock_payin_gateway():
    """Mock external Finunique Payin Gateway HTTP call."""
    with patch.object(settings, "PAYIN_URL", "https://api.finunique.com/payin"), \
         patch.object(settings, "PAYIN_TOKEN", "mock_payin_token_xyz"):

        original_post = AsyncClient.post

        async def mock_post(self, url, *args, **kwargs):
            url_str = str(url)
            if "finunique.com" in url_str:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "status": True,
                    "responseCode": "000",
                    "message": "Transaction Initiated",
                    "data": {
                        "redirectEx": "https://gateway.finunique.com/checkout/mock_session",
                        "redirectURL": "https://gateway.finunique.com/checkout/mock_session"
                    }
                }
                return resp
            return await original_post(self, url, *args, **kwargs)

        with patch("httpx.AsyncClient.post", new=mock_post):
            yield


async def create_user_with_token(db, role: str = "businessman", name: str = "Test User"):
    global _phone_counter
    _phone_counter += 1
    user_id = ObjectId()
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    phone_suffix = f"{random.randint(10000000, 99999999)}{_phone_counter % 10}"
    phone = f"+919{phone_suffix}"

    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": phone,
        "hashed_password": get_password_hash("Password@123"),
        "role": role,
        "phone_verified": True,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["users"].insert_one(user_doc)
    token = create_access_token(subject=str(user_id))
    return str(user_id), token, user_doc


async def mark_brand_kit_completed(db, user_id: str):
    """Sets Brand Kit completed for user in brand_kits and businesses collections."""
    now = datetime.now(timezone.utc)
    biz = await db["businesses"].find_one({"owner_id": user_id})
    if not biz:
        biz_id = ObjectId()
        await db["businesses"].insert_one({
            "_id": biz_id,
            "owner_id": user_id,
            "name": "Test Brand",
            "category": "Retail",
            "location": "Mumbai",
            "brand_kit_status": "completed",
            "brand_kit_completed": True,
            "brand_kit_completed_at": now,
            "created_at": now,
        })
    else:
        biz_id = biz["_id"]
        await db["businesses"].update_one(
            {"_id": biz_id},
            {"$set": {
                "brand_kit_status": "completed",
                "brand_kit_completed": True,
                "brand_kit_completed_at": now
            }}
        )

    await db["brand_kits"].update_one(
        {"owner_id": user_id},
        {"$set": {
            "owner_id": user_id,
            "business_id": biz_id,
            "business_name": "Test Brand",
            "brand_kit_status": "completed",
            "brand_kit_completed": True,
            "brand_kit_completed_at": now,
            "primary_color": "#7C3AED",
            "logo_url": "/uploads/brand/logo.png",
        }},
        upsert=True
    )


async def mark_social_media_connected(db, user_id: str, platform: str = "instagram"):
    """Connects at least one social media account and updates business doc."""
    now = datetime.now(timezone.utc)
    if platform == "instagram":
        await db["instagram_connections"].update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "platform": "instagram",
                "connected": True,
                "instagram_user_id": "1784140001",
                "instagram_username": "test_brand_ig",
                "created_at": now,
            }},
            upsert=True
        )
    elif platform == "facebook":
        await db["facebook_connections"].update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "platform": "facebook",
                "connected": True,
                "fb_page_id": "100200300",
                "fb_page_name": "Test FB Page",
                "created_at": now,
            }},
            upsert=True
        )
    elif platform == "linkedin":
        await db["linkedin_connections"].update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "platform": "linkedin",
                "connected": True,
                "linkedin_author_id": "urn:li:person:999",
                "display_name": "Test LinkedIn User",
                "created_at": now,
            }},
            upsert=True
        )

    await db["businesses"].update_one(
        {"owner_id": user_id},
        {"$set": {
            "social_connectivity_completed": True,
            "social_connectivity_completed_at": now,
            "connected_platforms": [platform],
            "updated_at": now
        }},
        upsert=True
    )


# --------------------------------------------------------------------------
# 1. Condition 1 & 3: Incomplete Brand Kit blocks Plan Onboarding
# --------------------------------------------------------------------------
async def test_plan_onboarding_ineligible_when_brand_kit_incomplete():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    # Brand Kit is NOT completed, even if social media is connected
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["brand_kit_completed"] is False
        assert data["social_connectivity_completed"] is True
        assert data["is_eligible"] is False
        assert data["should_show_modal"] is False


# --------------------------------------------------------------------------
# 2. Condition 2 & 3: Incomplete Social Media blocks Plan Onboarding
# --------------------------------------------------------------------------
async def test_plan_onboarding_ineligible_when_no_social_account_connected():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    # Brand Kit is completed, but 0 social accounts connected
    await mark_brand_kit_completed(db, user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["brand_kit_completed"] is True
        assert data["social_connectivity_completed"] is False
        assert data["is_eligible"] is False
        assert data["should_show_modal"] is False


# --------------------------------------------------------------------------
# 3. Condition 3 & 4: Both completed -> Plan Onboarding eligible & Modal opens
# --------------------------------------------------------------------------
async def test_plan_onboarding_eligible_modal_opens():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    # Complete Step 1 and Step 2
    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["brand_kit_completed"] is True
        assert data["social_connectivity_completed"] is True
        assert data["plan_activation_completed"] is False
        assert data["is_eligible"] is True
        assert data["should_show_modal"] is True
        assert len(data["available_plans"]) == 5
        assert data["billing_cycles"] == ["monthly", "quarterly", "yearly"]


# --------------------------------------------------------------------------
# 4. Condition 4 & 5: Popup reopens on refresh / declining popup doesn't mark complete
# --------------------------------------------------------------------------
async def test_modal_reopens_on_refresh_and_declining_does_not_complete():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "facebook")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # First check
        res1 = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res1.json()["should_show_modal"] is True
        assert res1.json()["plan_activation_completed"] is False

        # Simulate user closing popup or refreshing dashboard multiple times
        for _ in range(3):
            res_refresh = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
            assert res_refresh.json()["should_show_modal"] is True
            assert res_refresh.json()["plan_activation_completed"] is False


# --------------------------------------------------------------------------
# 5. Condition 8: Available plans, prices, periods, credits, and features match UI
# --------------------------------------------------------------------------
async def test_available_plans_and_pricing_structure():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/available-plans", headers=headers)
        assert res.status_code == 200
        plans = res.json()["data"]
        plan_ids = [p["id"] for p in plans]
        assert plan_ids == ["FREE", "STARTER", "GROWTH", "BUSINESS", "INFLUENCER"]

        # Check Starter
        starter = next(p for p in plans if p["id"] == "STARTER")
        assert starter["price"] == 799
        assert starter["credits"] == 100
        assert starter["billing_cycles"]["monthly"]["price"] == 799
        assert starter["billing_cycles"]["quarterly"]["price"] == 2157
        assert starter["billing_cycles"]["yearly"]["price"] == 7670
        assert len(starter["highlights"]) == 3

        # Check Growth
        growth = next(p for p in plans if p["id"] == "GROWTH")
        assert growth["price"] == 2999
        assert growth["credits"] == 400

        # Check Business
        business = next(p for p in plans if p["id"] == "BUSINESS")
        assert business["price"] == 4999
        assert business["credits"] == 1000

        # Check Influencer
        influencer = next(p for p in plans if p["id"] == "INFLUENCER")
        assert influencer["price"] == 9999
        assert influencer["credits"] == 2500


# --------------------------------------------------------------------------
# 6. Payment initiation (pending state does NOT complete onboarding)
# --------------------------------------------------------------------------
async def test_payment_initiation_keeps_plan_incomplete():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create payment for STARTER monthly
        pay_res = await ac.post("/api/v1/payments/payin/create", json={
            "plan_id": "STARTER",
            "billing_cycle": "monthly"
        }, headers=headers)
        assert pay_res.status_code == 200
        pay_data = pay_res.json()
        assert pay_data["success"] is True
        assert "ORDER_" in pay_data["order_id"]
        assert pay_data["status"] == "pending"

        # Onboarding status must still remain incomplete
        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert status_res.json()["plan_activation_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 7. Condition 6: Payment callback success marks onboarding complete & modal closes
# --------------------------------------------------------------------------
async def test_payment_callback_success_activates_plan_and_completes_step():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "linkedin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Initiate payment for GROWTH plan
        pay_res = await ac.post("/api/v1/payments/payin/create", json={
            "plan_id": "GROWTH",
            "billing_cycle": "monthly"
        }, headers=headers)
        order_id = pay_res.json()["order_id"]

        # 2. Receive successful payment callback
        callback_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 2999,
            "pgTransId": "PG_TXN_998877",
            "responseDescription": "Success"
        })
        assert callback_res.status_code == 200
        assert callback_res.json()["success"] is True
        assert callback_res.json()["status"] == "success"

        # 3. Check onboarding status: Step 3 is completed, modal ceases to show
        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        status_data = status_res.json()
        assert status_data["plan_activation_completed"] is True
        assert status_data["should_show_modal"] is False
        assert status_data["active_plan"]["plan_id"] == "GROWTH"
        assert status_data["active_plan"]["is_paid_plan"] is True


# --------------------------------------------------------------------------
# 8. Quarterly & Yearly billing cycles payment activation
# --------------------------------------------------------------------------
async def test_quarterly_and_yearly_billing_cycles_activation():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "facebook")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Quarterly Starter: ₹2,157
        pay_res = await ac.post("/api/v1/payments/payin/create", json={
            "plan_id": "STARTER",
            "billing_cycle": "quarterly"
        }, headers=headers)
        order_id = pay_res.json()["order_id"]

        # Verify transaction stored the quarterly amount and cycle
        txn = await db["payment_transactions"].find_one({"order_id": order_id})
        assert txn["amount"] == 2157.0
        assert txn["billing_cycle"] == "quarterly"

        # Successful callback
        cb_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 2157,
            "pgTransId": "PG_TXN_QUARTERLY_1"
        })
        assert cb_res.json()["success"] is True

        # Check plan activation
        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert status_res.json()["plan_activation_completed"] is True
        assert status_res.json()["active_plan"]["billing_cycle"] == "quarterly"
        assert status_res.json()["should_show_modal"] is False


# --------------------------------------------------------------------------
# 9. Failed payment callback handling
# --------------------------------------------------------------------------
async def test_failed_payment_callback():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "BUSINESS"}, headers=headers)
        order_id = pay_res.json()["order_id"]

        cb_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "102",
            "amount": 4999,
            "responseDescription": "Insufficient funds"
        })
        assert cb_res.json()["success"] is False
        assert cb_res.json()["status"] == "failed"

        # Modal should still show
        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert status_res.json()["plan_activation_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 10. Cancelled payment callback handling
# --------------------------------------------------------------------------
async def test_cancelled_payment_callback():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "STARTER"}, headers=headers)
        order_id = pay_res.json()["order_id"]

        cb_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "103",
            "responseDescription": "User cancelled payment"
        })
        assert cb_res.json()["success"] is False
        assert cb_res.json()["status"] == "cancelled"

        txn = await db["payment_transactions"].find_one({"order_id": order_id})
        assert txn["status"] == "cancelled"

        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert status_res.json()["plan_activation_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 11. Expired payment callback handling
# --------------------------------------------------------------------------
async def test_expired_payment_callback():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "GROWTH"}, headers=headers)
        order_id = pay_res.json()["order_id"]

        cb_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "104",
            "responseDescription": "Payment session expired"
        })
        assert cb_res.json()["success"] is False
        assert cb_res.json()["status"] == "expired"

        txn = await db["payment_transactions"].find_one({"order_id": order_id})
        assert txn["status"] == "expired"


# --------------------------------------------------------------------------
# 12. Amount Mismatch Tamper Protection
# --------------------------------------------------------------------------
async def test_amount_mismatch_rejected():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Starter costs ₹799
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "STARTER"}, headers=headers)
        order_id = pay_res.json()["order_id"]

        # Callback attempts to claim success with only ₹10
        cb_res = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 10.0,
            "pgTransId": "FAKE_TXN"
        })
        assert cb_res.json()["success"] is False
        assert "mismatch" in cb_res.json()["message"].lower()

        # Step remains incomplete
        status_res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert status_res.json()["plan_activation_completed"] is False
        assert status_res.json()["should_show_modal"] is True


# --------------------------------------------------------------------------
# 13. Idempotent Duplicate Callback Handling
# --------------------------------------------------------------------------
async def test_duplicate_callback_idempotency():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "STARTER"}, headers=headers)
        order_id = pay_res.json()["order_id"]

        # First callback: processes and succeeds
        cb1 = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 799,
            "pgTransId": "DUP_TXN_1"
        })
        assert cb1.json()["success"] is True

        # Second duplicate callback: should safely return already processed without doubling credits
        cb2 = await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 799,
            "pgTransId": "DUP_TXN_1"
        })
        assert cb2.status_code == 200
        assert cb2.json()["success"] is True
        assert "Already processed" in cb2.json()["message"]


# --------------------------------------------------------------------------
# 14. Influencer role bypasses Businessman Plan Onboarding modal
# --------------------------------------------------------------------------
async def test_influencer_role_bypasses_plan_onboarding():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="influencer", name="Influencer User")
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/subscription/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "influencer"
        assert data["should_show_modal"] is False
        assert data["plan_activation_completed"] is True


# --------------------------------------------------------------------------
# 15. Condition 7: Sidebar accessibility of Billing & Plans after onboarding
# --------------------------------------------------------------------------
async def test_sidebar_billing_and_plans_accessible_after_onboarding():
    db = get_database()
    user_id, token, _ = await create_user_with_token(db, role="businessman")
    headers = {"Authorization": f"Bearer {token}"}

    await mark_brand_kit_completed(db, user_id)
    await mark_social_media_connected(db, user_id, "instagram")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Complete plan activation
        pay_res = await ac.post("/api/v1/payments/payin/create", json={"plan_id": "BUSINESS"}, headers=headers)
        order_id = pay_res.json()["order_id"]
        await ac.post("/api/v1/payments/payin/callback", json={
            "orderId": order_id,
            "responseCode": "100",
            "amount": 4999,
            "pgTransId": "SIDEBAR_TXN"
        })

        # 2. Access /plans
        plans_res = await ac.get("/api/v1/subscription/plans", headers=headers)
        assert plans_res.status_code == 200
        assert "BUSINESS" in plans_res.json()["data"]

        # 3. Access /me (subscription & usage details)
        me_res = await ac.get("/api/v1/subscription/me", headers=headers)
        assert me_res.status_code == 200
        assert me_res.json()["data"]["plan_id"] == "BUSINESS"
        assert me_res.json()["data"]["plan_activation_completed"] is True

        # 4. Access /credits
        credits_res = await ac.get("/api/v1/subscription/credits", headers=headers)
        assert credits_res.status_code == 200
        assert credits_res.json()["credits_remaining"] >= 1000
