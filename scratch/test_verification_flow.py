import sys
import os
sys.path.insert(0, os.path.abspath("."))
import urllib.request
import json
import time

def test_full_email_verification():
    unique_email = f"verify_test_{int(time.time())}@example.com"
    signup_data = {
        "fullName": "Real Verification Test",
        "email": unique_email,
        "password": "Password@123",
        "accountType": "personal",
        "termsAccepted": True
    }

    
    signup_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/signup",
        data=json.dumps(signup_data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(signup_req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("1. Signup success:", data["message"])
            print("   emailVerified at signup:", data["data"]["user"]["emailVerified"])
    except urllib.error.HTTPError as e:
        print("Signup error:", e.code, e.read().decode())
        return

    # 2. Resend verification to jewelleryappdata (unverified mock user or test)
    # We can create a token for verify_test_01 and verify via JSON POST
    from app.services.auth_service import AuthService
    import asyncio
    from app.core.database import connect_to_mongo, get_database

    async def get_and_verify():
        connect_to_mongo()
        db = get_database()
        user = await db["users"].find_one({"email": unique_email})
        token = user.get("verificationToken")
        print("2. Got token from DB:", token[:30] + "...")

        # Test POST /api/v1/auth/verify-email
        verify_post_req = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/auth/verify-email",
            data=json.dumps({"token": token}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(verify_post_req) as resp:
            post_res = json.loads(resp.read().decode("utf-8"))
            print("3. POST /verify-email result:", post_res)

        # Check DB status
        user_after = await db["users"].find_one({"email": unique_email})
        print("4. User after verification in DB:")
        print("   emailVerified:", user_after.get("emailVerified"))
        print("   emailVerifiedAt:", user_after.get("emailVerifiedAt"))
        print("   verificationToken:", user_after.get("verificationToken"))

    asyncio.run(get_and_verify())

if __name__ == "__main__":
    test_full_email_verification()
