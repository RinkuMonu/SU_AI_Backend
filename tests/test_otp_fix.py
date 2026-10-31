import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from app.core.database import get_database
from app.services.auth_service import AuthService
from app.core.security import get_password_hash

@pytest.mark.asyncio
async def test_otp_verification_direct_and_idempotent():
    db = get_database()
    col = await AuthService.get_otp_collection()
    test_phone = "+917857889083"
    test_otp = "324056"
    now = datetime.now(timezone.utc)

    # 1. Clean previous state
    await col.delete_many({"phone_number": test_phone})

    # 2. Insert OTP doc with plain otp and hash
    otp_hash = get_password_hash(test_otp)
    await col.insert_one({
        "phone_number": test_phone,
        "otp": test_otp,
        "otp_hash": otp_hash,
        "channel": "sms",
        "mode": "login",
        "purpose": "login_verification",
        "expires_at": now + timedelta(minutes=10),
        "attempts": 0,
        "created_at": now,
        "recent_hashes": [{"otp_hash": otp_hash, "otp": test_otp, "channel": "sms", "expires_at": now + timedelta(minutes=10)}]
    })

    # 3. First verification call: should succeed and create phone_verification
    user = await AuthService.verify_phone_otp("+91-7857889083", test_otp)
    assert user is not None
    assert user.phone_number == test_phone

    # 4. Immediate second verification call (duplicate submit / race condition):
    # Should succeed idempotently via phone_verifications without throwing "OTP expired or invalid."
    user2 = await AuthService.verify_phone_otp("+91-7857889083", test_otp)
    assert user2 is not None
    assert user2.phone_number == test_phone

@pytest.mark.asyncio
async def test_otp_dev_test_bypass():
    # Number in TEST_DEVELOPER_NUMBERS should accept 123456
    user = await AuthService.verify_phone_otp("+91-7857889083", "123456")
    assert user is not None
    assert user.phone_number == "+917857889083"
