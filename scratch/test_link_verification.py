import sys
import os
sys.path.insert(0, os.path.abspath("."))
import urllib.request
import json
import asyncio
from app.core.database import connect_to_mongo, get_database

async def test_links():
    connect_to_mongo()
    db = get_database()
    await db["users"].update_one({"email": "jewelleryappdata@gmail.com"}, {"$set": {"emailVerified": False}})

    # 1. Resend verification
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/resend-verification",
        data=json.dumps({"email": "jewelleryappdata@gmail.com"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        resend_data = json.loads(resp.read().decode("utf-8"))
        print("1. Resend response data:")
        print("   verificationLink:", resend_data.get("data", {}).get("verificationLink"))

    full_link = resend_data["data"]["verificationLink"]

    # 2. Test POST /verify-email with {'link': full_link}
    verify_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/verify-email",
        data=json.dumps({"link": full_link}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(verify_req) as resp:
        print("2. Verify with {'link': full_link} status:", resp.status)
        print("   Verify response:", resp.read().decode("utf-8"))

    # 3. Test POST /verify-email with {'token': full_link}
    await db["users"].update_one({"email": "jewelleryappdata@gmail.com"}, {"$set": {"emailVerified": False}})
    verify_req2 = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/verify-email",
        data=json.dumps({"token": full_link}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(verify_req2) as resp:
        print("3. Verify with {'token': full_link} status:", resp.status)
        print("   Verify response:", resp.read().decode("utf-8"))

if __name__ == "__main__":
    asyncio.run(test_links())
