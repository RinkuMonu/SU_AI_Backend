import pytest
import pytest_asyncio
import asyncio
import jwt
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, get_database
from app.core.security import create_access_token, decode_access_token, get_current_user
from app.services.auth_service import AuthService
from app.services.msg91_email_service import Msg91EmailService
from app.schemas.auth import LoginRequest


@pytest_asyncio.fixture(scope="module")
async def db():
    connect_to_mongo()
    database = get_database()
    yield database
    close_mongo_connection()


@pytest.mark.asyncio
async def test_single_device_login_flow(db):
    test_user_id = str(ObjectId())
    test_email = f"single_device_{test_user_id[:8]}@example.com"

    # Insert a test user
    user_doc = {
        "_id": ObjectId(test_user_id),
        "name": "Single Device Tester",
        "email": test_email,
        "phone_number": "+919876543210",
        "role": "businessman",
        "phone_verified": True,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc)
    }
    await db["users"].insert_one(user_doc)

    try:
        with patch.object(Msg91EmailService, "_send_msg91_api", new_callable=AsyncMock) as mock_msg91:
            mock_msg91.return_value = {"success": True, "status": "SENT"}

            # 1. Device 1 logs in
            device1_info = {
                "device": "Google Chrome",
                "os": "Windows 11",
                "ip": "103.21.244.2",
                "location": "Jaipur, India"
            }

            token1, refresh1 = await AuthService.create_session(
                db=db,
                user_id=test_user_id,
                device_info=device1_info,
                send_login_email=True
            )
            await asyncio.sleep(0.3)

            # Verify MSG91 email called with correct template and variables
            assert mock_msg91.call_count == 1
            call_kwargs = mock_msg91.call_args_list[0][1]
            assert call_kwargs["template_id"] == "login_templete"
            assert call_kwargs["to_email"] == test_email
            vars_sent = call_kwargs["variables"]
            assert vars_sent["device"] == "Google Chrome"
            assert vars_sent["os"] == "Windows 11"
            assert vars_sent["ip"] == "103.21.244.2"
            assert vars_sent["location"] == "Jaipur, India"
            assert "secure_link" in vars_sent
            assert "support_email" in vars_sent
            assert "company_name" in vars_sent

            # Verify Device 1 token
            payload1 = decode_access_token(token1)
            assert payload1["sub"] == test_user_id
            sid1 = payload1.get("sid")
            assert sid1 is not None

            # Verify DB has active_session_id matching sid1
            db_user = await db["users"].find_one({"_id": ObjectId(test_user_id)})
            assert db_user["active_session_id"] == sid1
            assert db_user["active_device"]["device"] == "Google Chrome"

            # Device 1 can authenticate via get_current_user
            class MockRequest:
                cookies = {}
            class MockCreds:
                credentials = token1

            auth_user1 = await get_current_user(request=MockRequest(), credentials=MockCreds())
            assert auth_user1["id"] == test_user_id

            # 2. Device 2 logs in with the same account
            device2_info = {
                "device": "Mobile Safari",
                "os": "iOS (iPhone)",
                "ip": "49.36.120.5",
                "location": "Mumbai, India"
            }

            token2, refresh2 = await AuthService.create_session(
                db=db,
                user_id=test_user_id,
                device_info=device2_info,
                send_login_email=True
            )
            await asyncio.sleep(0.3)

            assert mock_msg91.call_count == 2
            vars_sent2 = mock_msg91.call_args_list[1][1]["variables"]
            assert vars_sent2["device"] == "Mobile Safari"
            assert vars_sent2["os"] == "iOS (iPhone)"
            assert vars_sent2["ip"] == "49.36.120.5"

            payload2 = decode_access_token(token2)
            sid2 = payload2.get("sid")
            assert sid2 is not None
            assert sid2 != sid1

            # Check DB active_session_id updated to sid2
            db_user2 = await db["users"].find_one({"_id": ObjectId(test_user_id)})
            assert db_user2["active_session_id"] == sid2

            # Device 2 authenticates successfully
            class MockCreds2:
                credentials = token2
            auth_user2 = await get_current_user(request=MockRequest(), credentials=MockCreds2())
            assert auth_user2["id"] == test_user_id

            # 3. Device 1 tries to access with old token -> MUST BE REJECTED (401)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request=MockRequest(), credentials=MockCreds())
            assert exc_info.value.status_code == 401
            assert "logged in on another device" in exc_info.value.detail.lower()

            # 4. Device 1 tries to refresh with old refresh token -> MUST BE REJECTED (401)
            with pytest.raises(HTTPException) as ref_exc:
                await AuthService.refresh(refresh1)
            assert ref_exc.value.status_code == 401
            assert "logged in on another device" in ref_exc.value.detail.lower()

            # 5. Device 2 refreshes -> MUST SUCCEED
            new_token2, new_refresh2 = await AuthService.refresh(refresh2)
            assert new_token2 is not None
            new_payload2 = decode_access_token(new_token2)
            assert new_payload2.get("sid") == sid2

    finally:
        # Cleanup test data
        await db["users"].delete_one({"_id": ObjectId(test_user_id)})
        await db["refresh_sessions"].delete_many({"userId": test_user_id})
