import sys
sys.path.insert(0, ".")
import asyncio
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.facebook_service import decrypt_token

async def inspect():
    connect_to_mongo()
    db = get_database()
    
    print("--- ALL USERS ---")
    async for u in db["users"].find():
        print(f"User: id={u.get('_id')} email={u.get('email')} name={u.get('name')} role={u.get('role')}")

    print("\n--- LATEST BUSINESSES WITH FB CONNECTED ---")
    async for b in db["businesses"].find({"fb_connected": True}).sort("_id", -1).limit(5):
        print("Business:", {
            "_id": str(b.get("_id")),
            "userId": b.get("userId"),
            "owner_id": b.get("owner_id"),
            "user_id": b.get("user_id"),
            "fb_page_id": b.get("fb_page_id"),
            "fb_page_name": b.get("fb_page_name"),
            "has_fb_access_token": bool(b.get("fb_access_token")),
            "has_encrypted": bool(b.get("fb_access_token_encrypted")),
            "fb_pages": b.get("fb_pages"),
        })
        
        # Test Graph API with this business's token!
        page_token = b.get("fb_access_token")
        page_id = b.get("fb_page_id")
        if page_token and page_id:
            import httpx
            async with httpx.AsyncClient() as client:
                # 1. Debug token
                debug_url = f"https://graph.facebook.com/debug_token?input_token={page_token}&access_token={page_token}"
                res = await client.get(debug_url)
                print("DEBUG TOKEN RESPONSE:")
                print(res.status_code, res.json())
                
                # 2. Check /me
                me_url = f"https://graph.facebook.com/v19.0/me?access_token={page_token}"
                res_me = await client.get(me_url)
                print("GET /me RESPONSE:")
                print(res_me.status_code, res_me.json())

                # 3. Check /me/permissions
                perm_url = f"https://graph.facebook.com/v19.0/me/permissions?access_token={page_token}"
                res_perm = await client.get(perm_url)
                print("GET /me/permissions RESPONSE:")
                print(res_perm.status_code, res_perm.json())
                
                # 4. Check page
                page_url = f"https://graph.facebook.com/v19.0/{page_id}?fields=id,name,access_token,tasks&access_token={page_token}"
                res_page = await client.get(page_url)
                print(f"GET /{page_id} RESPONSE:")
                print(res_page.status_code, res_page.json())

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(inspect())
