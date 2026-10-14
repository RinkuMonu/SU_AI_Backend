import sys
sys.path.insert(0, ".")
import asyncio
import httpx
from app.core.database import connect_to_mongo, get_database, close_mongo_connection

async def test_publish():
    connect_to_mongo()
    db = get_database()
    
    b = await db["businesses"].find_one({"fb_page_id": "627610063778275", "fb_access_token": {"$exists": True}})
    if not b:
        print("Business not found!")
        close_mongo_connection()
        return

    page_id = b["fb_page_id"]
    page_token = b["fb_access_token"]
    user_token = b.get("fb_user_access_token")

    print(f"Page ID: {page_id}")
    print(f"Page Token: {page_token[:20]}...")
    print(f"User Token: {user_token[:20] if user_token else 'None'}...")

    async with httpx.AsyncClient() as client:
        # Check permissions on user token if available
        if user_token:
            u_debug = await client.get(f"https://graph.facebook.com/debug_token?input_token={user_token}&access_token={user_token}")
            print("\nUser Token debug:", u_debug.status_code, u_debug.json())
            
            u_perms = await client.get(f"https://graph.facebook.com/v19.0/me/permissions?access_token={user_token}")
            print("\nUser Token permissions:", u_perms.status_code, u_perms.json())

            # Also check user's accounts from user_token
            u_accounts = await client.get(f"https://graph.facebook.com/v19.0/me/accounts?fields=id,name,access_token,tasks,perms&access_token={user_token}")
            print("\nUser accounts (/me/accounts):", u_accounts.status_code, u_accounts.json())

        # Now try to post text feed
        print("\nAttempting feed post with page_token...")
        res_feed = await client.post(
            f"https://graph.facebook.com/v19.0/{page_id}/feed",
            params={"message": "Test post from DhandaGrow AI", "access_token": page_token}
        )
        print("Feed post response:", res_feed.status_code, res_feed.text)

        # Try to post photo
        print("\nAttempting photo post with page_token...")
        res_photo = await client.post(
            f"https://graph.facebook.com/v19.0/{page_id}/photos",
            params={
                "url": "https://picsum.photos/400/300",
                "caption": "Test dummy image from DhandaGrow AI",
                "access_token": page_token
            }
        )
        print("Photo post response:", res_photo.status_code, res_photo.text)

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(test_publish())
