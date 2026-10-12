import sys
import os
sys.path.insert(0, os.path.abspath("."))
import urllib.request
import json
import asyncio
from app.core.database import connect_to_mongo, get_database

async def test_flow():
    connect_to_mongo()
    db = get_database()

    target_email = "jewelleryappdata@gmail.com"
    user = await db["users"].find_one({"email": target_email})
    if not user:
        print("User not found in DB!")
        return

    print("--- 1. Testing POST /api/v1/auth/forgot-password ---")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/forgot-password",
        data=json.dumps({"email": target_email}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        print("Forgot-password response:", resp.read().decode())

    user_updated = await db["users"].find_one({"email": target_email})
    token = user_updated.get("resetPasswordToken")
    print("Reset token in DB:", token[:30] + "..." if token else None)
    if not token:
        print("Error: No reset token created in DB!")
        return

    print("\n--- 2. Testing GET /api/v1/auth/reset-password?token=... ---")
    get_url = f"http://127.0.0.1:8000/api/v1/auth/reset-password?token={token}"
    get_req = urllib.request.Request(get_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(get_req) as resp:
        content = resp.read().decode()
        print("GET Status:", resp.status)
        print("Contains 'Set New Password':", "Set New Password" in content)
        print("Contains 'Confirm Password':", "Confirm Password" in content)
        print("Contains 'Dhanda Grow':", "Dhanda Grow" in content)

    print("\n--- 3. Testing POST /api/v1/auth/reset-password with mismatched passwords ---")
    mismatch_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/reset-password",
        data=json.dumps({
            "token": token,
            "newPassword": "password_A_123",
            "confirmPassword": "password_B_456"
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(mismatch_req)
        print("ERROR: Mismatch request should have failed!")
    except urllib.error.HTTPError as e:
        print("Correctly caught mismatch:", e.code, e.read().decode())

    print("\n--- 4. Testing POST /api/v1/auth/reset-password with matching passwords ---")
    new_pass = "DhandaGrow@2026"
    match_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/reset-password",
        data=json.dumps({
            "token": token,
            "newPassword": new_pass,
            "confirmPassword": new_pass
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(match_req) as resp:
        print("Success response:", resp.read().decode())

    print("\n--- 5. Testing Login with New Password ---")
    login_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/login",
        data=json.dumps({
            "email": target_email,
            "password": new_pass
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(login_req) as resp:
        login_res = json.loads(resp.read().decode())
        print("Login status:", login_res.get("success"), login_res.get("message"))
        print("Logged in as user:", login_res.get("data", {}).get("user", {}).get("email"))

if __name__ == "__main__":
    asyncio.run(test_flow())
