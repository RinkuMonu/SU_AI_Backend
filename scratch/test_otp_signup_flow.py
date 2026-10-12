import json
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import connect_to_mongo, get_database

async def run_test():
    connect_to_mongo()
    db = get_database()
    test_email = "testuser_sejal_flow@test.com"
    await db["users"].delete_many({"email": test_email})
    await db["otps"].delete_many({"email": test_email})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        print("--- 1. Testing send-otp / fallback mock OTP ---")
        try:
            resp = await client.post("/api/v1/auth/send-otp", json={"email": test_email, "name": "Sejal Gupta"})
            print("Send OTP Response Status:", resp.status_code)
            print("Send OTP Body:", resp.json())
        except Exception as e:
            print("Send OTP error:", e)

        # Set or get OTP
        await db["otps"].update_one(
            {"email": test_email},
            {"$set": {"email": test_email, "otp": "654321", "verified": False}},
            upsert=True
        )
        otp = "654321"

        print("--- 2. Testing verify-otp ---")
        resp_verify = await client.post("/api/v1/auth/verify-otp", json={"email": test_email, "otp": otp})
        print("Verify OTP Status:", resp_verify.status_code)
        print("Verify OTP Response:", resp_verify.json())
        assert resp_verify.status_code == 200

        print("--- 3. Testing signup with firstName, lastName, contactNumber, otp ---")
        signup_payload = {
            "firstName": "Sejal",
            "lastName": "Gupta",
            "contactNumber": "+91 98765 43210",
            "email": test_email,
            "password": "SecurePassword123!",
            "otp": otp
        }
        resp_signup = await client.post("/api/v1/auth/signup", json=signup_payload)
        print("Signup Status:", resp_signup.status_code)
        print("Signup Response:")
        print(json.dumps(resp_signup.json(), indent=2))
        assert resp_signup.status_code == 200

        # Check user in DB
        user = await db["users"].find_one({"email": test_email})
        print("\n--- 4. Verified User Document in MongoDB ---")
        print(f"fullName: {user.get('fullName')}")
        print(f"firstName: {user.get('firstName')}")
        print(f"lastName: {user.get('lastName')}")
        print(f"phone / contactNumber: {user.get('phone')} / {user.get('contactNumber')}")
        print(f"emailVerified: {user.get('emailVerified')}")
        print(f"email_verified: {user.get('email_verified')}")

        assert user.get("firstName") == "Sejal"
        assert user.get("lastName") == "Gupta"
        assert user.get("fullName") == "Sejal Gupta"
        assert user.get("contactNumber") == "+91 98765 43210"
        assert user.get("emailVerified") is True

        # Clean up
        await db["users"].delete_many({"email": test_email})
        await db["otps"].delete_many({"email": test_email})
        print("\nCleanup completed. TEST PASSED!")

if __name__ == "__main__":
    asyncio.run(run_test())

