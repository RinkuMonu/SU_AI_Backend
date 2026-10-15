import sys
sys.path.insert(0, ".")
import asyncio
import httpx
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.facebook_service import decrypt_token

async def check():
    connect_to_mongo()
    db = get_database()
    
    b = await db['businesses'].find_one({"_id": ObjectId("6ace05ca1e06924210923576")})
    user_token = b.get("fb_user_access_token")
    page_token = b.get("fb_access_token")
    page_id = b.get("fb_page_id")

    print(f"Page ID: {page_id}")
    print(f"User Token len: {len(user_token) if user_token else 0}")
    print(f"Page Token len: {len(page_token) if page_token else 0}")

    async with httpx.AsyncClient() as client:
        # Check /me/accounts with user_token
        r = await client.get(
            f"https://graph.facebook.com/v19.0/me/accounts?fields=id,name,access_token,tasks,category&access_token={user_token}"
        )
        print("me/accounts status:", r.status_code)
        data = r.json()
        print("me/accounts data:", data)

        for p in data.get("data", []):
            ptoken = p.get("access_token")
            pid = p.get("id")
            tasks = p.get("tasks")
            print(f"\nPage {p.get('name')} ({pid}) tasks: {tasks}")
            deb = await client.get(f"https://graph.facebook.com/debug_token?input_token={ptoken}&access_token={ptoken}")
            print("Page token scopes:", deb.json().get("data", {}).get("scopes"))

            # Check if this page token can post photo
            post_test = await client.post(
                f"https://graph.facebook.com/v19.0/{pid}/photos",
                params={
                    "url": "https://picsum.photos/400/300",
                    "caption": "Test Post from DhandaGrow AI",
                    "access_token": ptoken
                }
            )
            print("Post test result:", post_test.status_code, post_test.text)

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(check())
