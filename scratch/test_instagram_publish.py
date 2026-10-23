import asyncio
import httpx
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.instagram_service import InstagramService
from app.core.security import create_access_token

async def main():
    connect_to_mongo()
    db = get_database()
    
    # 1. Check users
    users = await db["users"].find().to_list(10)
    print(f"Total users found: {len(users)}")
    target_user = None
    for u in users:
        uid = str(u["_id"])
        email = u.get("email", "no-email")
        ig_conn = await InstagramService.get_connection(db, uid)
        print(f"User {uid} ({email}): ig_connected={u.get('instagram_connected')} -> conn={ig_conn is not None}")
        if ig_conn:
            print(f"   IG details: {ig_conn.get('instagram_user_id')}, {ig_conn.get('instagram_username')}")
            target_user = u
            
    if not target_user and users:
        target_user = users[0]
        
    if not target_user:
        print("No users in DB!")
        return

    uid = str(target_user["_id"])
    email = target_user.get("email", "test@example.com")
    token = create_access_token(subject=uid)
    print(f"\nUsing test user: {email} (id: {uid})")

    # 2. Test Instagram publish endpoint via HTTP request to localhost:8000
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "image_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80",
        "caption": "Test Instagram Post from DhandaGrow AI automated diagnostic test"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test /api/v1/instagram/publish-image
        try:
            print("\nTesting POST http://127.0.0.1:8000/api/v1/instagram/publish-image ...")
            res = await client.post("http://127.0.0.1:8000/api/v1/instagram/publish-image", json=payload, headers=headers)
            print(f"Status: {res.status_code}")
            print(f"Response: {res.text}")
        except Exception as e:
            print(f"HTTP request error: {e}")
            
        # Also test InstagramService.publish_image directly
        print("\nTesting InstagramService.publish_image directly ...")
        try:
            result = await InstagramService.publish_image(
                db=db,
                user_id=uid,
                image_url=payload["image_url"],
                caption=payload["caption"]
            )
            print(f"Direct publish result: {result}")
        except Exception as e:
            print(f"Direct publish exception: {type(e).__name__}: {e}")

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(main())
