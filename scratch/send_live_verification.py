import sys
import os
sys.path.insert(0, os.path.abspath("."))
import urllib.request
import json
import asyncio
from app.core.database import connect_to_mongo, get_database

async def send_live():
    connect_to_mongo()
    db = get_database()
    await db["users"].update_one(
        {"email": "jewelleryappdata@gmail.com"},
        {"$set": {"emailVerified": False, "verificationToken": None}}
    )
    print("1. Set jewelleryappdata@gmail.com emailVerified = False in database")

    # Call API to send verification email
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/resend-verification",
        data=json.dumps({"email": "jewelleryappdata@gmail.com"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        print("2. Resend API Response:", resp.read().decode("utf-8"))

    user = await db["users"].find_one({"email": "jewelleryappdata@gmail.com"})
    token = user.get("verificationToken")
    print("3. Generated Token:", token)
    print("4. Verification Link in Email:", f"http://localhost:8000/api/v1/auth/verify-email?token={token}")

if __name__ == "__main__":
    asyncio.run(send_live())
