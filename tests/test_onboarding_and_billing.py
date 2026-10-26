import io
import uuid
import random
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import get_password_hash, create_access_token
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService
from app.services.payin_service import PayinService

pytestmark = pytest.mark.asyncio

_counter = 8000


@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


async def create_test_user(db, role: str = "businessman", name: str = "Test User"):
    global _counter
    _counter += 1
    user_id = ObjectId()
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    phone = f"+919{random.randint(10000000, 99999999)}"

    user_doc = {
        "_id": user_id,
        "name": name,
        "email": email,
        "phone_number": phone,
        "hashed_password": get_password_hash("SecretPass@123"),
        "role": role,
        "phone_verified": True,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["users"].insert_one(user_doc)
    token = create_access_token(subject=str(user_id))
    return str(user_id), token, user_doc


# ==============================================================================
# 1. Saving a Brand Kit with only two fields
# ==============================================================================
async def test_1_save_brand_kit_with_two_fields():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Two Fields User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Submit only 2 fields: business_name and tagline
        payload = {
            "business_name": "Apex Micro Dynamics",
            "tagline": "Empowering local businesses"
        }

        res = await ac.post("/api/v1/brands", json=payload, headers=headers)
        assert res.status_code in [200, 201], f"Expected 200/201, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["success"] is True
        assert data["brand_kit_status"] == "in_progress"
        assert data["brand_kit_completed"] is False
        assert data["completion_percentage"] > 0

        # Verify MongoDB persistence
        brand_doc = await db["brand_kits"].find_one({"owner_id": user_id})
        assert brand_doc is not None
        assert brand_doc["business_name"] == "Apex Micro Dynamics"
        assert brand_doc["tagline"] == "Empowering local businesses"
        # Optional fields must NOT be populated with fake data
        assert brand_doc.get("website") is None or brand_doc.get("website") == ""


# ==============================================================================
# 2. Updating a partial profile without erasing existing values
# ==============================================================================
async def test_2_update_partial_profile_preserves_existing():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Update User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Step A: Initial save with 3 fields
        res1 = await ac.post("/api/v1/brands", json={
            "business_name": "Vertex Digital",
            "tagline": "Pioneering the web",
            "primary_color": "#2563EB"
        }, headers=headers)
        assert res1.status_code in [200, 201]

        # Step B: Partial update with only font and website (omitting tagline, primary_color)
        res2 = await ac.put("/api/v1/brands", json={
            "font": "Inter",
            "website": "https://vertexdigital.ai"
        }, headers=headers)
        assert res2.status_code == 200

        # Step C: Read back from DB to verify preservation
        brand_doc = await db["brand_kits"].find_one({"owner_id": user_id})
        assert brand_doc["business_name"] == "Vertex Digital"
        assert brand_doc["tagline"] == "Pioneering the web"
        assert brand_doc["primary_color"] == "#2563EB"
        assert brand_doc["font"] == "Inter"
        assert brand_doc["website"] == "https://vertexdigital.ai"

        # Step D: Update with empty string on optional field must NOT erase existing value
        res3 = await ac.put("/api/v1/brands", json={"tagline": ""}, headers=headers)
        assert res3.status_code == 200
        brand_doc_after = await db["brand_kits"].find_one({"owner_id": user_id})
        assert brand_doc_after["tagline"] == "Pioneering the web"


# ==============================================================================
# 3. Saving an incomplete Influencer profile
# ==============================================================================
async def test_3_saving_incomplete_influencer_profile():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="influencer", name="Influencer Star")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Partial save: bio and category only
        partial_influencer = {
            "bio": "Lifestyle and fitness creator based in Mumbai.",
            "category": "Fitness"
        }

        res = await ac.put("/api/v1/influencer/me", json=partial_influencer, headers=headers)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()["data"]
        assert data["bio"] == "Lifestyle and fitness creator based in Mumbai."
        assert data["category"] == "Fitness"
        assert data.get("profile_completion", 0) > 0

        # Verify MongoDB persistence
        prof_doc = await db["influencer_profiles"].find_one({"user_id": user_id})
        assert prof_doc is not None
        assert prof_doc["bio"] == "Lifestyle and fitness creator based in Mumbai."

        # Update price without erasing bio
        res2 = await ac.put("/api/v1/influencer/me", json={"expectedPricePerPost": 15000}, headers=headers)
        assert res2.status_code == 200
        prof_doc2 = await db["influencer_profiles"].find_one({"user_id": user_id})
        assert prof_doc2["bio"] == "Lifestyle and fitness creator based in Mumbai."
        assert prof_doc2["expectedPricePerPost"] == 15000


# ==============================================================================
# 4. Connecting one social account and persisting its status
# ==============================================================================
async def test_4_connecting_one_social_account_persists():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Social User")

    # Connect Instagram account in DB
    now = datetime.now(timezone.utc)
    await db["instagram_connections"].update_one(
        {"user_id": user_id, "platform": "instagram"},
        {"$set": {
            "connected": True,
            "account_id": "ig_123456",
            "account_name": "my_business_page",
            "access_token": "token_abc",
            "connected_at": now,
            "updated_at": now
        }},
        upsert=True
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["social_connectivity_completed"] is True
        assert data["connected_count"] >= 1
        assert data["platforms"]["instagram"]["connected"] is True
        assert data["should_show_modal"] is False


# ==============================================================================
# 5. Skipping social connectivity and resuming onboarding
# ==============================================================================
async def test_5_skipping_social_connectivity_resumes_onboarding():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Skip User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # User skips social step
        skip_res = await ac.post("/api/v1/social/skip", headers=headers)
        assert skip_res.status_code == 200
        assert skip_res.json()["social_connectivity_skipped"] is True

        # Check DB persistence
        biz = await db["businesses"].find_one({"owner_id": user_id})
        assert biz is not None
        assert biz.get("social_connectivity_skipped") is True

        # Check onboarding status: modal must not show
        status_res = await ac.get("/api/v1/social/onboarding-status", headers=headers)
        assert status_res.status_code == 200
        assert status_res.json()["should_show_modal"] is False


# ==============================================================================
# 6. Activating a free plan and displaying the ₹0 record
# ==============================================================================
async def test_6_activating_free_plan_displays_zero_record():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Free Plan User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Activate Free plan
        res = await ac.post("/api/v1/subscription/activate-free", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True

        # Verify subscription history has ₹0 record
        hist_doc = await db["subscription_history"].find_one({"user_id": user_id, "plan_id": "FREE"})
        assert hist_doc is not None
        assert hist_doc["amount"] == 0
        assert hist_doc["currency"] == "INR"
        assert hist_doc["is_free"] is True
        assert hist_doc["invoice_reference"].startswith("INV-FREE-")

        # Verify NO fake payment transaction exists
        tx_count = await db["payment_transactions"].count_documents({"user_id": user_id})
        assert tx_count == 0

        # Verify billing report displays this ₹0 record
        report_res = await ac.get("/api/v1/subscription/billing-report", headers=headers)
        assert report_res.status_code == 200
        report = report_res.json()["data"]
        assert len(report["subscription_history"]) >= 1
        free_entry = next(h for h in report["subscription_history"] if h["plan_id"] == "FREE")
        assert free_entry["amount"] == 0
        assert free_entry["is_free"] is True


# ==============================================================================
# 7. Purchasing a ₹799 plan and recording confirmed transaction
# ==============================================================================
async def test_7_purchasing_799_plan_records_confirmed_transaction():
    db = get_database()
    user_id, token, user_doc = await create_test_user(db, role="businessman", name="Growth Plan User")

    now = datetime.now(timezone.utc)
    order_id = f"ORDER_TEST_799_{uuid.uuid4().hex[:6]}"
    
    # 799 base + 18% GST = 942.82
    tx_doc = {
        "user_id": user_id,
        "plan_id": "GROWTH",
        "plan_name": "Growth Plan",
        "base_amount": 799.0,
        "gst_rate": 0.18,
        "gst_amount": 143.82,
        "billing_cycle": "monthly",
        "amount": 942.82,
        "currency": "INR",
        "order_id": order_id,
        "status": "initiated",
        "created_at": now,
        "updated_at": now
    }
    await db["payment_transactions"].insert_one(tx_doc)

    # Simulate payment callback confirmation
    callback_payload = {
        "orderId": order_id,
        "amount": 942.82,
        "responseCode": "100",
        "status": "SUCCESS",
        "pgTransId": "PG_TXN_799_CONFIRMED"
    }
    result = await PayinService.process_callback(db, callback_payload)
    assert result["success"] is True

    # Verify payment transaction is confirmed
    updated_tx = await db["payment_transactions"].find_one({"order_id": order_id})
    assert updated_tx["status"] == "success"
    assert updated_tx["external_transaction_id"] == "PG_TXN_799_CONFIRMED"

    # Verify subscription upgraded to GROWTH
    sub = await db["subscriptions"].find_one({"user_id": user_id})
    assert sub["plan_id"] == "GROWTH"
    assert sub["status"] == "active"

    # Verify subscription_history record exists
    hist = await db["subscription_history"].find_one({"user_id": user_id, "transaction_id": order_id})
    assert hist is not None
    assert hist["plan_id"] == "GROWTH"
    assert hist["amount"] == 942.82
    assert hist["payment_status"] == "paid"


# ==============================================================================
# 8. Recording AI credits granted and consumed
# ==============================================================================
async def test_8_recording_credits_granted_and_consumed():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Credit User")

    # 1. Grant 50 credits
    grant_res = await CreditService.grant_credits(
        db, user_id, 50,
        reason="promotional_grant",
        reference_id="grant_ref_001"
    )
    assert grant_res["credits_remaining"] >= 50

    # 2. Consume 1 credit
    consume_res = await CreditService.deduct_credits(db, user_id, "post_caption")
    assert consume_res["success"] is True

    # 3. Retrieve summary
    summary = await CreditService.get_credit_summary(db, user_id)
    assert summary["credits_consumed"] >= 1
    assert summary["credits_remaining"] >= 49

    # 4. Check ledger audit trail
    history = await CreditService.get_history(db, user_id)
    types = [tx["transaction_type"] for tx in history]
    assert "grant" in types
    assert "deduction" in types


# ==============================================================================
# 9. Preventing duplicate subscriptions, credit grants, and transactions
# ==============================================================================
async def test_9_preventing_duplicate_subscriptions_and_credit_grants():
    db = get_database()
    user_id, token, _ = await create_test_user(db, role="businessman", name="Idempotent User")

    order_id = f"ORDER_IDEMP_{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc)
    await db["payment_transactions"].insert_one({
        "user_id": user_id,
        "plan_id": "STARTER",
        "plan_name": "Starter Plan",
        "amount": 299.0,
        "billing_cycle": "monthly",
        "currency": "INR",
        "order_id": order_id,
        "status": "initiated",
        "created_at": now,
        "updated_at": now
    })

    callback_payload = {
        "orderId": order_id,
        "amount": 299.0,
        "responseCode": "100",
        "status": "SUCCESS",
        "pgTransId": "PG_IDEMP_123"
    }

    # First callback execution
    res1 = await PayinService.process_callback(db, callback_payload)
    assert res1["success"] is True

    sub_after_1 = await db["subscriptions"].find_one({"user_id": user_id})
    credits_after_1 = sub_after_1["credits_remaining"]
    history_count_1 = await db["subscription_history"].count_documents({"user_id": user_id, "transaction_id": order_id})
    assert history_count_1 == 1

    # Second callback execution (retry)
    res2 = await PayinService.process_callback(db, callback_payload)
    assert res2["success"] is True
    assert "already processed" in res2["message"].lower()

    # Verify no duplicate credit grant
    sub_after_2 = await db["subscriptions"].find_one({"user_id": user_id})
    assert sub_after_2["credits_remaining"] == credits_after_1

    # Verify no duplicate subscription history record
    history_count_2 = await db["subscription_history"].count_documents({"user_id": user_id, "transaction_id": order_id})
    assert history_count_2 == 1


# ==============================================================================
# 10. Retrieving accurate onboarding and billing reports after fresh login
# ==============================================================================
async def test_10_accurate_onboarding_and_billing_after_fresh_login():
    db = get_database()
    user_id, initial_token, _ = await create_test_user(db, role="businessman", name="Session User")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_init = {"Authorization": f"Bearer {initial_token}"}

        # Step 1: Save Brand Kit partial
        await ac.post("/api/v1/brands", json={
            "business_name": "Fresh Login Enterprise",
            "tagline": "Persistence assured"
        }, headers=headers_init)

        # Step 2: Skip social connectivity
        await ac.post("/api/v1/social/skip", headers=headers_init)

        # Step 3: Activate Free plan
        await ac.post("/api/v1/subscription/activate-free", headers=headers_init)

        # Simulate logout and fresh login: create new access token
        fresh_token = create_access_token(subject=user_id)
        headers_fresh = {"Authorization": f"Bearer {fresh_token}"}

        # Fetch onboarding status after fresh login
        onb_res = await ac.get("/api/v1/onboarding/status", headers=headers_fresh)
        assert onb_res.status_code == 200
        onb_data = onb_res.json()

        assert onb_data["steps"]["step_1_brand_kit"]["status"] == "in_progress"
        assert onb_data["steps"]["step_1_brand_kit"]["should_show_modal"] is False
        assert onb_data["steps"]["step_2_social_connectivity"]["status"] == "skipped"
        assert onb_data["steps"]["step_2_social_connectivity"]["should_show_modal"] is False
        assert onb_data["steps"]["step_3_subscription_plan"]["status"] == "completed"
        assert onb_data["steps"]["step_3_subscription_plan"]["should_show_modal"] is False
        assert onb_data["current_modal_to_show"] is None

        # Fetch billing report after fresh login
        bill_res = await ac.get("/api/v1/subscription/billing-report", headers=headers_fresh)
        assert bill_res.status_code == 200
        bill_data = bill_res.json()["data"]

        assert bill_data["user_id"] == user_id
        assert bill_data["current_subscription"]["plan_id"] == "FREE"
        assert len(bill_data["subscription_history"]) >= 1
        assert bill_data["credit_summary"]["credits_remaining"] >= 5
