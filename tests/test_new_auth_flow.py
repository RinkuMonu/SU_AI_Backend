import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from bson import ObjectId

from app.main import app
from app.core.config import settings
from app.core.database import get_database, connect_to_mongo
from app.core.security import get_password_hash, create_access_token
from app.services.sms_service import SMSService
from app.services.google_service import GoogleService

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
async def clean_database():
    connect_to_mongo()
    db = get_database()
    test_phones = ["+919111122222", "+919222233333", "+919333344444", "+919444455555", "+919555566666", "+919666677777"]
    test_emails = ["newuser@example.com", "existing@example.com", "googleuser@example.com", "dupemail@example.com", "dupphone@example.com"]
    await db["users"].delete_many({"$or": [{"phone_number": {"$in": test_phones}}, {"email": {"$in": test_emails}}]})
    await db["otps"].delete_many({"phone_number": {"$in": test_phones}})
    await db["phone_verifications"].delete_many({"phone_number": {"$in": test_phones}})
    await db["refresh_sessions"].delete_many({})
    yield
    await db["users"].delete_many({"$or": [{"phone_number": {"$in": test_phones}}, {"email": {"$in": test_emails}}]})
    await db["otps"].delete_many({"phone_number": {"$in": test_phones}})
    await db["phone_verifications"].delete_many({"phone_number": {"$in": test_phones}})
    await db["refresh_sessions"].delete_many({})

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# =====================================================================
# 1. MOBILE OTP (Fast2SMS) & MSG91 WHATSAPP OTP TESTS
# =====================================================================
async def test_fast2sms_clean_extraction_and_delivery_simulation():
    """Verify Fast2SMS 10-digit number extraction and SMS route handling."""
    assert SMSService.extract_clean_10_digits("+919111122222") == "9111122222"
    assert SMSService.extract_clean_10_digits("09111122222") == "9111122222"
    assert SMSService.extract_clean_10_digits("9111122222") == "9111122222"

    # Explicitly test Fast2SMS method from Deepak's branch
    f2s_res = await SMSService._send_via_fast2sms("+919111122222", "123456", channel="sms")
    assert f2s_res.get("success") is True
    assert f2s_res.get("simulated") is True or f2s_res.get("return") is True

    # Test send_otp routing with SMS
    res = await SMSService.send_otp("+919111122222", "123456", channel="sms")
    assert res.get("success") is True



async def test_msg91_whatsapp_otp_payload_and_template_contract():
    """Verify MSG91 WhatsApp OTP endpoint, template name, namespace, and variable mapping."""
    captured_requests = []

    async def mock_handler(request: httpx.Request):
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            json={"type": "success", "message": "Message sent successfully", "request_id": "wa_req_998877"}
        )

    transport = httpx.MockTransport(mock_handler)
    with patch("app.core.config.settings.MSG91_WHATSAPP_AUTHKEY", "test_msg91_whatsapp_secret_key"):
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            res = await SMSService.send_otp("+919111122222", "654321", channel="whatsapp")
            assert res.get("success") is True
            assert res.get("channel") == "whatsapp"

    assert len(captured_requests) >= 1
    req = captured_requests[0]
    assert req.url == "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/"
    assert req.headers.get("authkey") == "test_msg91_whatsapp_secret_key"
    
    import json
    body = json.loads(req.content.decode("utf-8"))
    assert body["integrated_number"] == "917733886507"
    assert body["payload"]["template"]["name"] == "otp_template"
    assert body["payload"]["template"]["language"]["code"] == "en"
    assert body["payload"]["template"]["namespace"] == "a84d2159_8fa6_4354_9967_74f013129d57"
    
    comp = body["payload"]["template"]["to_and_components"][0]["components"]
    assert comp["body_1"]["value"] == "654321"


async def test_msg91_whatsapp_delivery_failure_raises_clear_error():
    """Return clear errors when MSG91 delivery fails."""
    async def mock_fail_handler(request: httpx.Request):
        return httpx.Response(
            status_code=400,
            json={"type": "error", "message": "Invalid Template Variable Count"}
        )

    transport = httpx.MockTransport(mock_fail_handler)
    with patch("app.core.config.settings.MSG91_WHATSAPP_AUTHKEY", "test_msg91_whatsapp_secret_key"):
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await SMSService.send_otp("+919111122222", "654321", channel="whatsapp")
            assert exc_info.value.status_code == 502
            assert "WhatsApp delivery failed" in exc_info.value.detail


# =====================================================================
# 2. OTP LIFECYCLE & SECURITY (EXPIRY, COOLDOWN, ATTEMPTS, SINGLE-USE)
# =====================================================================
async def test_otp_resend_cooldown_60_seconds(client):
    test_phone = "+919111122222"
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True}
        # First send
        res1 = await client.post("/api/v1/auth/send-otp", json={
            "phone_number": test_phone,
            "channel": "sms",
            "mode": "signup"
        })
        assert res1.status_code == 200

        # Resend before 60s cooldown -> 429 Too Many Requests
        res2 = await client.post("/api/v1/auth/send-otp", json={
            "phone_number": test_phone,
            "channel": "sms",
            "mode": "signup"
        })
        assert res2.status_code == 429
        assert "60 seconds" in res2.json()["detail"]


async def test_otp_attempt_limits_lockout_and_single_use(client):
    test_phone = "+919222233333"
    db = get_database()
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True}
        # Generate OTP
        await client.post("/api/v1/auth/send-otp", json={
            "phone_number": test_phone,
            "channel": "whatsapp",
            "mode": "signup"
        })

    # Set fixed OTP
    await db["otps"].update_one(
        {"phone_number": test_phone},
        {"$set": {"otp_hash": get_password_hash("778899")}}
    )

    # 1. Invalid OTP attempts
    bad_res = await client.post("/api/v1/auth/verify-otp", json={
        "phone_number": test_phone,
        "otp": "000000"
    })
    assert bad_res.status_code == 400
    assert "Invalid OTP" in bad_res.json()["detail"]

    # 2. Simulate 5 failed attempts -> 6th triggers lockout & deletes OTP
    await db["otps"].update_one(
        {"phone_number": test_phone},
        {"$set": {"attempts": 5}}
    )
    lock_res = await client.post("/api/v1/auth/verify-otp", json={
        "phone_number": test_phone,
        "otp": "778899"
    })
    assert lock_res.status_code == 400
    assert "Too many failed attempts" in lock_res.json()["detail"]
    assert await db["otps"].find_one({"phone_number": test_phone}) is None


async def test_otp_expiry(client):
    test_phone = "+919333344444"
    db = get_database()
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True}
        await client.post("/api/v1/auth/send-otp", json={"phone_number": test_phone, "mode": "signup"})

    # Expire OTP
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db["otps"].update_one({"phone_number": test_phone}, {"$set": {"expires_at": past}})

    res = await client.post("/api/v1/auth/verify-otp", json={"phone_number": test_phone, "otp": "123456"})
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()


# =====================================================================
# 3. NEW SIGNUP FLOW (PHONE OTP -> GOOGLE AUTH -> EXACTLY ONE USER)
# =====================================================================
async def test_new_signup_flow_via_sms_and_google_auth(client):
    test_phone = "+919444455555"
    db = get_database()

    # Step 1: Send SMS OTP
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True}
        res1 = await client.post("/api/v1/auth/send-otp", json={
            "phone_number": test_phone,
            "channel": "sms",
            "mode": "signup"
        })
        assert res1.status_code == 200

    # Set known hash
    await db["otps"].update_one({"phone_number": test_phone}, {"$set": {"otp_hash": get_password_hash("112233")}})

    # Step 2: Verify Phone OTP
    res2 = await client.post("/api/v1/auth/verify-otp", json={
        "phone_number": test_phone,
        "otp": "112233",
        "channel": "sms",
        "mode": "signup"
    })
    assert res2.status_code == 200
    v_data = res2.json()
    assert v_data["phone_verified"] is True
    v_token = v_data["phone_verification_token"]
    assert v_token is not None

    # Step 3: Complete Google Authorization for Signup
    fake_google_user = {
        "email": "newuser@example.com",
        "sub": "google_sub_123456",
        "given_name": "Sejal",
        "family_name": "Gupta",
        "name": "Sejal Gupta",
        "picture": "https://example.com/avatar.jpg"
    }
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g_info:
        mock_g_info.return_value = fake_google_user
        res3 = await client.post("/api/v1/auth/google/signup", json={
            "access_token": "valid_google_token",
            "phone_verification_token": v_token
        })
        assert res3.status_code == 200
        signup_res = res3.json()
        assert signup_res["success"] is True
        assert signup_res["requires_role_selection"] is True
        assert signup_res["dashboard_route"] == "/select-role"
        assert "access_token" in signup_res
        user_jwt = signup_res["access_token"]

    # Exactly ONE user document in 'users' collection
    users_found = await db["users"].find({"phone_number": test_phone}).to_list(10)
    assert len(users_found) == 1
    new_user = users_found[0]
    assert new_user["email"] == "newuser@example.com"
    assert new_user["phone_verified"] is True
    assert new_user["email_verified"] is True
    assert new_user["googleId"] == "google_sub_123456"
    assert new_user["role"] is None, "New user role must be None until /select-role"

    # Step 4: Role selection through /select-role flow
    res4 = await client.post(
        "/api/v1/auth/select-role",
        headers={"Authorization": f"Bearer {user_jwt}"},
        json={"role": "businessman"}
    )
    assert res4.status_code == 200
    assert res4.json()["role"] == "businessman"

    # Confirm role is persisted
    updated_user = await db["users"].find_one({"_id": new_user["_id"]})
    assert updated_user["role"] == "businessman"


async def test_new_signup_flow_via_whatsapp_otp(client):
    """Either Fast2SMS OTP OR MSG91 WhatsApp OTP satisfies phone-verification step."""
    test_phone = "+919555566666"
    db = get_database()

    # WhatsApp send
    with patch.object(SMSService, "send_otp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "channel": "whatsapp"}
        res1 = await client.post("/api/v1/auth/send-otp", json={
            "phone_number": test_phone,
            "channel": "whatsapp",
            "mode": "signup"
        })
        assert res1.status_code == 200
        assert res1.json()["channel"] == "whatsapp"

    await db["otps"].update_one({"phone_number": test_phone}, {"$set": {"otp_hash": get_password_hash("334455")}})

    # Verify WhatsApp OTP
    res2 = await client.post("/api/v1/auth/verify-otp", json={
        "phone_number": test_phone,
        "otp": "334455",
        "channel": "whatsapp",
        "mode": "signup"
    })
    assert res2.status_code == 200
    assert res2.json()["phone_verified"] is True
    v_token = res2.json()["phone_verification_token"]
    assert v_token is not None

    # Complete Google signup
    fake_google_user = {
        "email": "googleuser@example.com",
        "sub": "google_sub_789012",
        "name": "WhatsApp Google User",
        "picture": "https://example.com/pic.png"
    }
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g_info:
        mock_g_info.return_value = fake_google_user
        res3 = await client.post("/api/v1/auth/google/signup", json={
            "access_token": "valid_token",
            "phone_verification_token": v_token
        })
        assert res3.status_code == 200
        assert res3.json()["user"]["phone_verified"] is True
        assert res3.json()["user"]["email"] == "googleuser@example.com"


# =====================================================================
# 4. CONFLICT & DUPLICATE CHECKS (HTTP 409)
# =====================================================================
async def test_duplicate_phone_number_signup_rejected_with_409(client):
    test_phone = "+919666677777"
    db = get_database()
    # Insert existing account
    await db["users"].insert_one({
        "name": "Existing Account",
        "phone_number": test_phone,
        "phone_verified": True,
        "email": "existing@example.com",
        "email_verified": True
    })

    # 1. Sending signup OTP for existing phone returns 409
    res1 = await client.post("/api/v1/auth/send-otp", json={
        "phone_number": test_phone,
        "channel": "sms",
        "mode": "signup"
    })
    assert res1.status_code == 409
    assert "already exists" in res1.json()["detail"]

    # 2. Resend signup OTP returns 409
    res2 = await client.post("/api/v1/auth/resend-otp", json={
        "phone_number": test_phone,
        "mode": "signup"
    })
    assert res2.status_code == 409

    # 3. Google signup with existing phone returns 409
    token = "simulated_verification_token"
    await db["phone_verifications"].insert_one({
        "phone_number": test_phone,
        "verification_token": token,
        "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)
    })
    fake_google = {"email": "fresh_email@example.com", "sub": "fresh_sub_1"}
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g:
        mock_g.return_value = fake_google
        res3 = await client.post("/api/v1/auth/google/signup", json={
            "access_token": "valid_token",
            "phone_verification_token": token
        })
        assert res3.status_code == 409
        assert "already exists" in res3.json()["detail"]


async def test_duplicate_google_email_signup_rejected_with_409(client):
    test_phone = "+919444455555"
    db = get_database()
    # Insert existing user with email
    await db["users"].insert_one({
        "name": "Email Owner",
        "email": "dupemail@example.com",
        "phone_number": "+919111122222",
        "email_verified": True
    })

    token = "token_for_dup_email_test"
    await db["phone_verifications"].insert_one({
        "phone_number": test_phone,
        "verification_token": token,
        "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)
    })
    fake_google = {"email": "dupemail@example.com", "sub": "fresh_sub_2"}
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g:
        mock_g.return_value = fake_google
        res = await client.post("/api/v1/auth/google/signup", json={
            "access_token": "valid_token",
            "phone_verification_token": token
        })
        assert res.status_code == 409
        assert "already exists" in res.json()["detail"]


# =====================================================================
# 5. EXISTING USER LOGIN & NO SILENT CREATION
# =====================================================================
async def test_existing_google_user_logs_in_without_signup_steps(client):
    db = get_database()
    await db["users"].insert_one({
        "name": "Returning User",
        "email": "existing@example.com",
        "googleId": "existing_google_id_999",
        "role": "businessman",
        "phone_number": "+919111122222",
        "phone_verified": True,
        "email_verified": True,
        "onboardingCompleted": True
    })

    fake_google = {"email": "existing@example.com", "sub": "existing_google_id_999"}
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g:
        mock_g.return_value = fake_google
        res = await client.post("/api/v1/auth/google/login", json={
            "access_token": "valid_token",
            "mode": "login"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["role"] == "businessman"
        assert "access_token" in data


async def test_google_login_never_silently_creates_account(client):
    db = get_database()
    await db["users"].delete_many({"email": "unregistered@example.com"})
    await db["pending_users"].delete_many({"email": "unregistered@example.com"})
    fake_google = {"email": "unregistered@example.com", "sub": "unregistered_sub_888"}
    with patch.object(GoogleService, "get_user_info", new_callable=AsyncMock) as mock_g:
        mock_g.return_value = fake_google
        res = await client.post("/api/v1/auth/google/login", json={
            "access_token": "valid_token",
            "mode": "login"
        })
        assert res.status_code == 404
        assert "sign up first" in res.json()["detail"].lower()
